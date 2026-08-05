import datetime

from django.test import TestCase
from django.utils import timezone

from repo.api.retention import apply_retention_policy, apply_retention_policy_repo
from repo.models import Package, Repository


def _make_repo(repo_uid, policy="none", keep_count=None, max_age_days=None):
    return Repository.objects.create(
        repo_uid=repo_uid,
        repo_type="deb",
        retention_policy=policy,
        retention_keep_count=keep_count,
        retention_max_age_days=max_age_days,
    )


def _make_package(repo, name, version, arch="amd64", days_ago=0):
    upload_date = timezone.now() - datetime.timedelta(days=days_ago)
    uid = f"{repo.repo_uid}-{name}-{version}-{arch}".replace(" ", "-")
    return Package.objects.create(
        repo=repo,
        package_uid=uid,
        filename=f"{name}_{version}_{arch}.deb",
        package_name=name,
        architecture=arch,
        version=version,
        upload_date=upload_date,
        checksum_sha512=uid,
    )


class RetentionPolicyNoneTest(TestCase):
    def test_none_policy_keeps_all(self):
        repo = _make_repo("r-none", policy=Repository.RETENTION_NONE)
        for v in ["1.0", "2.0", "3.0"]:
            _make_package(repo, "nginx", v)
        apply_retention_policy(repo, "nginx", "amd64")
        self.assertEqual(Package.objects.filter(repo=repo).count(), 3)


class RetentionKeepLatestNTest(TestCase):
    def test_keeps_n_newest(self):
        repo = _make_repo("r-kln", policy=Repository.RETENTION_KEEP_LATEST_N, keep_count=2)
        # Newest first in upload_date
        _make_package(repo, "nginx", "3.0", days_ago=1)
        _make_package(repo, "nginx", "2.0", days_ago=2)
        _make_package(repo, "nginx", "1.0", days_ago=3)
        apply_retention_policy(repo, "nginx", "amd64")
        remaining = list(Package.objects.filter(repo=repo).values_list("version", flat=True))
        self.assertEqual(sorted(remaining), ["2.0", "3.0"])

    def test_under_limit_unchanged(self):
        repo = _make_repo("r-kln2", policy=Repository.RETENTION_KEEP_LATEST_N, keep_count=5)
        _make_package(repo, "nginx", "1.0")
        _make_package(repo, "nginx", "2.0")
        apply_retention_policy(repo, "nginx", "amd64")
        self.assertEqual(Package.objects.filter(repo=repo).count(), 2)

    def test_per_arch_independent(self):
        """keep_latest_n applies per (package_name, architecture) independently."""
        repo = _make_repo("r-kln3", policy=Repository.RETENTION_KEEP_LATEST_N, keep_count=1)
        _make_package(repo, "nginx", "1.0", arch="amd64", days_ago=2)
        _make_package(repo, "nginx", "2.0", arch="amd64", days_ago=1)
        _make_package(repo, "nginx", "1.0", arch="arm64", days_ago=2)
        _make_package(repo, "nginx", "2.0", arch="arm64", days_ago=1)
        apply_retention_policy(repo, "nginx", "amd64")
        apply_retention_policy(repo, "nginx", "arm64")
        # Should keep 1 per arch = 2 total
        self.assertEqual(Package.objects.filter(repo=repo).count(), 2)
        remaining = list(Package.objects.filter(repo=repo).values_list("version", flat=True))
        self.assertEqual(remaining, ["2.0", "2.0"])


class RetentionMaxAgeDaysTest(TestCase):
    def test_deletes_old_packages(self):
        repo = _make_repo("r-age", policy=Repository.RETENTION_MAX_AGE_DAYS, max_age_days=30)
        _make_package(repo, "nginx", "1.0", days_ago=60)
        _make_package(repo, "nginx", "2.0", days_ago=10)
        apply_retention_policy(repo, "nginx", "amd64")
        remaining = list(Package.objects.filter(repo=repo).values_list("version", flat=True))
        self.assertEqual(remaining, ["2.0"])

    def test_all_recent_kept(self):
        repo = _make_repo("r-age2", policy=Repository.RETENTION_MAX_AGE_DAYS, max_age_days=30)
        _make_package(repo, "nginx", "1.0", days_ago=5)
        _make_package(repo, "nginx", "2.0", days_ago=10)
        apply_retention_policy(repo, "nginx", "amd64")
        self.assertEqual(Package.objects.filter(repo=repo).count(), 2)


class RetentionKeepLatestNAndAgeTest(TestCase):
    def test_union_removes_by_either_rule(self):
        repo = _make_repo(
            "r-both",
            policy=Repository.RETENTION_KEEP_LATEST_N_AND_AGE,
            keep_count=2,
            max_age_days=20,
        )
        # v3: newest, 5 days old — kept by count, kept by age
        _make_package(repo, "nginx", "3.0", days_ago=5)
        # v2: 15 days old — kept by count (top 2), kept by age
        _make_package(repo, "nginx", "2.0", days_ago=15)
        # v1: 30 days old — removed by count (beyond 2) AND by age
        _make_package(repo, "nginx", "1.0", days_ago=30)
        apply_retention_policy(repo, "nginx", "amd64")
        remaining = list(Package.objects.filter(repo=repo).values_list("version", flat=True))
        self.assertEqual(sorted(remaining), ["2.0", "3.0"])

    def test_age_removes_even_if_within_count(self):
        """A package within the count limit but older than max_age is still removed."""
        repo = _make_repo(
            "r-both2",
            policy=Repository.RETENTION_KEEP_LATEST_N_AND_AGE,
            keep_count=3,
            max_age_days=10,
        )
        _make_package(repo, "nginx", "3.0", days_ago=2)
        _make_package(repo, "nginx", "2.0", days_ago=5)
        _make_package(repo, "nginx", "1.0", days_ago=20)  # within count=3 but too old
        apply_retention_policy(repo, "nginx", "amd64")
        remaining = list(Package.objects.filter(repo=repo).values_list("version", flat=True))
        self.assertEqual(sorted(remaining), ["2.0", "3.0"])


class RetentionCrossRepoProtectionTest(TestCase):
    """Q4 A: packages referenced by another repo must not be deleted."""

    def test_skips_package_in_another_repo(self):
        repo_a = _make_repo("r-cross-a", policy=Repository.RETENTION_KEEP_LATEST_N, keep_count=1)
        repo_b = _make_repo("r-cross-b")

        # Same package_uid in both repos (as happens after package_copy)
        shared_uid = "shared-nginx-1-0-amd64"
        Package.objects.create(
            repo=repo_a, package_uid=shared_uid,
            filename="nginx_1.0_amd64.deb", package_name="nginx",
            architecture="amd64", version="1.0",
            upload_date=timezone.now() - datetime.timedelta(days=5),
            checksum_sha512=shared_uid,
        )
        Package.objects.create(
            repo=repo_b, package_uid=shared_uid,
            filename="nginx_1.0_amd64.deb", package_name="nginx",
            architecture="amd64", version="1.0",
            upload_date=timezone.now() - datetime.timedelta(days=5),
            checksum_sha512=shared_uid,
        )
        Package.objects.create(
            repo=repo_a, package_uid="nginx-2-0-amd64",
            filename="nginx_2.0_amd64.deb", package_name="nginx",
            architecture="amd64", version="2.0",
            upload_date=timezone.now(),
            checksum_sha512="nginx-2-0-amd64",
        )

        apply_retention_policy(repo_a, "nginx", "amd64")

        # v2.0 kept (newest), v1.0 should NOT be deleted from repo_a because
        # repo_b still holds the same package_uid
        self.assertTrue(Package.objects.filter(repo=repo_a, version="1.0").exists())
        self.assertTrue(Package.objects.filter(repo=repo_b, version="1.0").exists())


class RetentionRepoSweepTest(TestCase):
    def test_repo_sweep_covers_all_groups(self):
        repo = _make_repo("r-sweep", policy=Repository.RETENTION_KEEP_LATEST_N, keep_count=1)
        _make_package(repo, "nginx", "1.0", arch="amd64", days_ago=2)
        _make_package(repo, "nginx", "2.0", arch="amd64", days_ago=1)
        _make_package(repo, "curl", "7.0", arch="amd64", days_ago=2)
        _make_package(repo, "curl", "8.0", arch="amd64", days_ago=1)
        apply_retention_policy_repo(repo)
        self.assertEqual(Package.objects.filter(repo=repo).count(), 2)
        versions = set(Package.objects.filter(repo=repo).values_list("version", flat=True))
        self.assertEqual(versions, {"2.0", "8.0"})
