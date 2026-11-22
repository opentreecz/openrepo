# SPDX-License-Identifier: AGPL-3.0-only
import base64
import gzip
import hashlib
import json
import os
import time
import uuid
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from adapters.repo.apk_repo import _write_apkindex_tar_gz
from repo.storage_audit import audit
from repo.tasks import storage_audit_task
from repo.tests.test_cleanup import CleanupFixtureMixin


class StorageAuditTests(CleanupFixtureMixin, APITestCase):
    def test_preserves_references_and_separates_recovery_copies(self):
        root = Path(self.publish_dir("deb.00001"))
        (Path(self.www_path) / "deb").symlink_to(root)
        directory = root / "dists/stable/main/binary-any"
        directory.mkdir(parents=True)
        pool = root / "pool"
        pool.mkdir()
        name = "a~1 +x_%20.deb"
        kept = self.storage_file("zz/kept")
        (pool / name).symlink_to(kept)
        (pool / "unindexed.deb").symlink_to(kept)
        self.package("zz-kept")
        self.storage_file("zz/db")
        self.package("zz-db")
        self.storage_file("zz/upload")
        self.upload_task("zz/upload", age_hours=240)
        self.storage_file("zz/recent", age=time.time())
        old = time.time() - 9 * 86400
        self.storage_file("zz/recovery", age=old, size=29)
        self.storage_file("zz/unused", age=old, size=50)
        for rel in ("kept", "db", "upload"):
            os.utime(Path(self.storage_path) / "zz" / rel, (old, old))
        records = "".join(f"Filename: pool/{file}\nSHA256: {hashlib.sha256(b'x'*n).hexdigest()}\n\n"
                          for file, n in [(name, 10), ("renamed.deb", 29)])
        (directory / "Packages").write_text(records)
        buf = StringIO()
        report = audit(buf)
        rows = [json.loads(line) for line in buf.getvalue().splitlines()]
        self.assertEqual(report["candidate_bytes"], 50)
        self.assertEqual({(r["kind"], r["path"]) for r in rows}, {
            ("Indexed file missing", "deb/pool/renamed.deb"),
            ("Filename needs review", "deb/pool/" + name),
            ("Published but not indexed", "deb/pool/unindexed.deb"),
            ("Database package not reached by index", "zz/db"),
            ("Possible recovery copy", "zz/recovery"),
            ("Unreferenced storage candidate", "zz/unused"),
        })
        self.assertTrue((Path(self.storage_path) / "zz/unused").exists())

    def test_missing_generation_prevents_candidate_classification(self):
        self.storage_file("zz/unused", age=time.time() - 10 * 86400)
        report = audit(StringIO())
        self.assertEqual(report["candidate_bytes"], 0)
        self.assertEqual(report["counts"], {"Incomplete": 1, "Unverified storage file": 1})

    def test_rpm_index_url_decodes_once_preserving_plus_and_literal_percent(self):
        self.repo.repo_type = "rpm"
        self.repo.save()
        root = Path(self.publish_dir("deb.00001"))
        (Path(self.www_path) / "deb").symlink_to(root)
        metadata = root / "x86_64/repodata"
        metadata.mkdir(parents=True)
        (metadata / "repomd.xml").write_text(
            '<repomd><data type="primary"><location href="repodata/primary.xml.gz"/></data></repomd>'
        )
        target = self.storage_file("zz/kept")
        (metadata.parent / "a ~+_%20.rpm").symlink_to(target)
        digest = hashlib.sha256(b"x" * 10).hexdigest()
        with gzip.open(metadata / "primary.xml.gz", "wt") as stream:
            stream.write(f'<metadata><package><checksum type="sha256">{digest}</checksum>'
                         '<location href="a%20~+_%2520.rpm"/></package></metadata>')
        self.assertEqual(audit(StringIO())["counts"], {"Filename needs review": 1})

    def test_missing_generic_download_with_no_checksum_blocks_candidates(self):
        self.repo.repo_type = "files"
        self.repo.save()
        root = Path(self.publish_dir("deb.00001"))
        (Path(self.www_path) / "deb").symlink_to(root)
        (root / "index.html").write_text('<a href="file%20name.bin">download</a>')
        (root / "file-name.bin").symlink_to(self.storage_file("zz/kept"))
        self.storage_file("xx/old", age=time.time() - 9 * 86400)
        report = audit(StringIO())
        self.assertEqual(report["candidate_bytes"], 0)
        self.assertEqual(report["counts"]["Indexed file missing"], 1)
        self.assertEqual(report["counts"]["Unverified storage file"], 1)
        warning = next(row for row in report["preview"] if row["kind"] == "Filename needs review")
        self.assertEqual(warning["path"], "deb/file-name.bin")
        self.assertEqual(warning["advertised"], ["file%20name.bin"])

    def test_filtered_pages_preserve_exact_paths_including_invalid_bytes(self):
        job = uuid.uuid4()
        directory = Path(self.var_dir) / "storage-audits"
        directory.mkdir()
        bad = os.fsdecode(b"file-\xff")
        records = [{"kind": "Filename needs review", "path": f"{bad}{i}"} for i in range(56)]
        with (directory / f"{job}.jsonl").open("w") as out:
            for row in [{"kind": "Incomplete", "path": "file-other"}] + records:
                out.write(json.dumps(row) + "\n")
        self.client.force_authenticate(get_user_model().objects.create_superuser(username="auditor"))
        url = f"/api/maintenance/storage-audits/{job}/findings/"
        filters = {"search": "FILE-", "kind": "Filename needs review"}
        first = self.client.get(url, filters).json()
        second = self.client.get(url, {**filters, "after": first["next"]}).json()
        self.assertEqual(len(first["rows"]), 50)
        self.assertEqual(first["rows"] + second["rows"], records)
        self.assertIsNone(second["next"])
        self.assertEqual(self.client.get(url, {"after": 2}).status_code, 400)

    def test_apk_recovery_uses_advertised_name_and_checksum(self):
        self.repo.repo_type = "apk"
        self.repo.save()
        root = Path(self.publish_dir("deb.00001"))
        (Path(self.www_path) / "deb").symlink_to(root)
        checksum = base64.b64encode(hashlib.sha1(b"x" * 10).digest()).decode()
        _write_apkindex_tar_gz(root, f"C:Q1{checksum}\nP:demo\nV:1-r1\nA:x86_64\n", "deb")
        self.storage_file("zz/old", age=time.time() - 9 * 86400)
        report = audit(StringIO())
        self.assertEqual(report["counts"], {"Indexed file missing": 1, "Possible recovery copy": 1})
        self.assertEqual(report["preview"][-1]["matches"], ["deb/demo-1-r1.apk"])

    def test_worker_manifest_and_superuser_boundary(self):
        job = str(uuid.uuid4())
        base = "/api/maintenance/storage-audits/"
        worker_report = storage_audit_task(job)
        user = get_user_model().objects.create_user(username="viewer")
        self.client.force_authenticate(user)
        self.assertEqual(self.client.post(base).status_code, 403)
        for suffix in ("", "manifest/", "findings/"):
            self.assertEqual(self.client.get(base + job + "/" + suffix).status_code, 403)
        user.is_superuser = True
        response = self.client.get(base + job + "/manifest/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(b"".join(response.streaming_content)), worker_report["preview"][0])
        with patch.object(storage_audit_task, "apply_async") as queue:
            response = self.client.post(base)
            self.assertEqual(response.status_code, 202)
            audit_id = response.data["id"]
            queue.assert_called_once_with(args=[audit_id], task_id=f"storage-audit-{audit_id}")
        with patch.object(storage_audit_task, "AsyncResult") as job_result:
            job_result.return_value.state = "SUCCESS"
            job_result.return_value.result = worker_report
            response = self.client.get(base + job + "/")
            self.assertEqual(response.data["report"], worker_report)
