# Copyright 2022 by Open Kilt LLC. All rights reserved.
# This file is part of the OpenRepo Repository Management Software (OpenRepo)
# OpenRepo is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License
# version 3 as published by the Free Software Foundation
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import string

from django.contrib.auth.models import User
from rest_framework import serializers

from adapters.repo import get_repo_adapter
from repo.models import Build, BuildLogLine, Package, PGPSigningKey, Repository, UploadTask

from .util import ParameterisedHyperlinkedIdentityField


class UserSerializer(serializers.HyperlinkedModelSerializer):
    """User account summary (public fields only)."""

    class Meta:
        model = User
        fields = ["href", "username", "is_superuser", "email"]
        extra_kwargs = {
            "username": {"help_text": "Unique login name."},
            "is_superuser": {"help_text": "Whether the user has full admin privileges."},
            "email": {"help_text": "Email address."},
        }


class UserDetailSerializer(serializers.HyperlinkedModelSerializer):
    """User account with API key (returned by /api/whoami)."""

    api_key = serializers.StringRelatedField(
        source="auth_token", read_only=True, many=False,
        help_text="API authentication token for this user.",
    )

    class Meta:
        model = User
        fields = ["href", "username", "is_superuser", "email", "api_key"]
        extra_kwargs = {
            "username": {"help_text": "Unique login name."},
            "is_superuser": {"help_text": "Whether the user has full admin privileges."},
            "email": {"help_text": "Email address."},
        }


class RepoSummarySerializer(serializers.HyperlinkedModelSerializer):
    """Repository overview used in list views."""

    href_repo = ParameterisedHyperlinkedIdentityField(
        view_name="repo-detail", lookup_fields=([("repo_uid", "repo_uid")]), read_only=True,
        help_text="URL to the full repository detail.",
    )
    href_packages = ParameterisedHyperlinkedIdentityField(
        view_name="package-list", lookup_fields=([("repo_uid", "repo_uid")]), read_only=True,
        help_text="URL to the package list for this repository.",
    )
    promote_to = serializers.SlugRelatedField(
        slug_field="repo_uid", read_only=True, allow_null=True,
        help_text="Target repository for package promotion (null if disabled).",
    )

    class Meta:
        model = Repository
        fields = [
            "href_repo",
            "href_packages",
            "repo_uid",
            "repo_type",
            "package_count",
            "is_stale",
            "last_updated",
            "promote_to",
        ]
        extra_kwargs = {
            "repo_uid": {"help_text": "Unique identifier slug for the repository."},
            "repo_type": {"help_text": "Package format: deb, rpm, apk, or files."},
            "package_count": {"help_text": "Number of packages in the repository."},
            "is_stale": {"help_text": "True if repo metadata needs regeneration."},
            "last_updated": {"help_text": "Timestamp of the last package change."},
        }


class PGPKeySerializer(serializers.HyperlinkedModelSerializer):
    """PGP signing key metadata."""

    class Meta:
        model = PGPSigningKey
        lookup_field = "fingerprint"
        extra_kwargs = {
            "href": {"lookup_field": "fingerprint"},
            "name": {"help_text": "Full name associated with the PGP key."},
            "email": {"help_text": "Email address associated with the PGP key."},
            "fingerprint": {"help_text": "40-character hex PGP key fingerprint."},
            "creation_date": {"help_text": "When the key was generated."},
        }
        fields = ["name", "email", "fingerprint", "creation_date", "href"]
        read_only_fields = ["creation_date"]


class RepoDetailSerializer(serializers.HyperlinkedModelSerializer):
    """Full repository detail with configuration and instructions."""

    href_packages = ParameterisedHyperlinkedIdentityField(
        view_name="package-list", lookup_fields=([("repo_uid", "repo_uid")]), read_only=True,
        help_text="URL to the package list for this repository.",
    )
    href_upload = ParameterisedHyperlinkedIdentityField(
        view_name="upload", lookup_fields=([("repo_uid", "repo_uid")]), read_only=True,
        help_text="URL for uploading packages to this repository.",
    )

    signing_key = serializers.SlugRelatedField(
        slug_field="fingerprint", queryset=PGPSigningKey.objects.all(),
        read_only=False, required=False, allow_null=True,
        help_text="PGP key fingerprint used to sign this repository.",
    )
    promote_to = serializers.SlugRelatedField(
        slug_field="repo_uid", queryset=Repository.objects.all(),
        read_only=False, required=False, allow_null=True,
        help_text="Target repository for package promotion.",
    )

    write_access = serializers.StringRelatedField(
        read_only=True, many=True,
        help_text="Users with write access to this repository.",
    )

    repo_instructions = serializers.SerializerMethodField(
        help_text="Shell commands for configuring a client to use this repository.",
    )

    class Meta:
        model = Repository
        fields = [
            "href_packages",
            "href_upload",
            "repo_uid",
            "repo_type",
            "package_count",
            "is_stale",
            "signing_key",
            "retention_policy",
            "retention_keep_count",
            "retention_max_age_days",
            "multi_arch",
            "last_updated",
            "promote_to",
            "repo_instructions",
            "write_access",
        ]
        extra_kwargs = {
            "repo_uid": {"help_text": "Unique identifier slug for the repository."},
            "repo_type": {"help_text": "Package format: deb, rpm, apk, or files."},
            "package_count": {"help_text": "Number of packages in the repository."},
            "is_stale": {"help_text": "True if repo metadata needs regeneration.", "read_only": True},
            "retention_policy": {"help_text": "Retention strategy (none, keep_latest_n, keep_latest_age, keep_latest_n_and_age)."},
            "retention_keep_count": {"help_text": "Number of versions to keep (when using keep_latest_n policy)."},
            "retention_max_age_days": {"help_text": "Maximum age in days (when using keep_latest_age policy)."},
            "multi_arch": {"help_text": "Whether to generate per-architecture metadata (deb/rpm only)."},
            "last_updated": {"help_text": "Timestamp of the last package change."},
        }

    def get_repo_instructions(self, obj) -> str:
        repo_adapter = get_repo_adapter(obj)
        return repo_adapter._get_repo_instructions()

    def validate(self, attrs):
        # repo_uid validation only applies when repo_uid is provided (create or full update)
        if "repo_uid" in attrs:
            allowed_uid_chars = set(string.ascii_letters + string.digits + "-_")

            uuid_is_valid = set(attrs["repo_uid"]) <= allowed_uid_chars
            if not uuid_is_valid:
                raise serializers.ValidationError(
                    {"repo_uid": "repo_uid may only contain alphanumeric characters, dashes, and underscores"}
                )

            disallowed_names = [
                "back", "api", "admin", "api-auth", "static",
                "users", "repos", "signingkeys", "builds", "buildlogs",
                "whoami", "upload-status", "packages", "pkg",
            ]
            if attrs["repo_uid"] in disallowed_names:
                raise serializers.ValidationError(
                    {"repo_uid": "Repo UID cannot be any of the following special words: " + ", ".join(disallowed_names)}
                )

        # signing_key required only on create
        if self.instance is None and (attrs.get("signing_key") is None or attrs.get("signing_key") == ""):
            raise serializers.ValidationError({"signing_key": "Signing key is required"})

        # Default multi_arch to True for new deb and rpm repos (unless explicitly set to False)
        if self.instance is None and attrs.get("repo_type") in ("deb", "rpm"):
            if "multi_arch" not in self.initial_data:
                attrs["multi_arch"] = True

        promote_to = attrs.get("promote_to")
        if promote_to:
            # Prevent circular promotion chains
            if self.instance:
                current = promote_to
                while current is not None:
                    if current.pk == self.instance.pk:
                        raise serializers.ValidationError(
                            {
                                "promote_to": f"Setting promote_to to '{promote_to.repo_uid}' would create "
                                "a circular promotion chain"
                            }
                        )
                    current = current.promote_to

        return attrs


class PackageSummarySerializer(serializers.HyperlinkedModelSerializer):
    """Package overview used in list views."""

    href_package = ParameterisedHyperlinkedIdentityField(
        view_name="package-detail",
        lookup_fields=([("repo.repo_uid", "repo_uid"), ("package_uid", "package_uid")]),
        read_only=True,
        help_text="URL to the full package detail.",
    )

    class Meta:
        model = Package
        fields = ["href_package", "package_uid", "package_name", "filename", "architecture", "upload_date", "version"]
        extra_kwargs = {
            "package_uid": {"help_text": "Unique identifier slug for the package."},
            "package_name": {"help_text": "Parsed package name (e.g. 'nginx')."},
            "filename": {"help_text": "Original uploaded filename."},
            "architecture": {"help_text": "Target architecture (e.g. amd64, arm64, all)."},
            "upload_date": {"help_text": "When the package was uploaded."},
            "version": {"help_text": "Package version string."},
        }


class PackageDetailSerializer(serializers.HyperlinkedModelSerializer):
    """Full package detail including checksums and build date."""

    repo_uid = serializers.StringRelatedField(
        source="repo", read_only=True,
        help_text="Repository this package belongs to.",
    )

    class Meta:
        model = Package
        fields = [
            "package_uid",
            "repo_uid",
            "package_name",
            "filename",
            "version",
            "architecture",
            "checksum_sha512",
            "build_date",
            "upload_date",
        ]
        extra_kwargs = {
            "package_uid": {"help_text": "Unique identifier slug for the package."},
            "package_name": {"help_text": "Parsed package name (e.g. 'nginx')."},
            "filename": {"help_text": "Original uploaded filename."},
            "version": {"help_text": "Package version string."},
            "architecture": {"help_text": "Target architecture (e.g. amd64, arm64, all)."},
            "checksum_sha512": {"help_text": "SHA-512 hash of the package file."},
            "build_date": {"help_text": "When the package was built (from package metadata)."},
            "upload_date": {"help_text": "When the package was uploaded to OpenRepo."},
        }


class CopySerializer(serializers.Serializer):
    """Request body for copying a package to another repository."""

    dest_repo_uid = serializers.CharField(help_text="Target repository UID to copy the package to.")

    class Meta:
        fields = ["dest_repo_uid"]


class UploadSerializer(serializers.Serializer):
    """Multipart form data for package upload."""

    package_file = serializers.FileField(help_text="The package file to upload (.deb, .rpm, or any file).")
    overwrite = serializers.CharField(required=False, help_text='Set to "1", "true", or "yes" to overwrite existing.')

    class Meta:
        fields = ["package_file", "overwrite"]


class UploadResponseSerializer(serializers.Serializer):
    """Response returned by the upload endpoint (HTTP 202 Accepted)."""
    task_id = serializers.UUIDField(help_text="ID for polling upload status via /api/upload-status/<task_id>/")


class ErrorResponseSerializer(serializers.Serializer):
    """Standard error envelope returned by all API error responses."""
    code = serializers.CharField(help_text="Machine-readable error code (e.g. PACKAGE_EXISTS)")
    detail = serializers.CharField(help_text="Human-readable error description")
    status = serializers.IntegerField(help_text="HTTP status code")


class PGPKeyCreateRequestSerializer(serializers.Serializer):
    """Request body for generating a new PGP signing key."""
    name = serializers.CharField(help_text="Full name for the PGP key (1-1024 characters)")
    email = serializers.EmailField(help_text="Email address for the PGP key")


class UploadTaskSerializer(serializers.ModelSerializer):
    """Upload task status returned by the polling endpoint."""

    repo_uid = serializers.CharField(
        source="repo.repo_uid", read_only=True,
        help_text="Repository this upload belongs to.",
    )

    class Meta:
        model = UploadTask
        fields = [
            "id",
            "repo_uid",
            "status",
            "filename",
            "filesize",
            "sha512",
            "error_message",
            "error_code",
            "result_data",
            "created_at",
            "completed_at",
        ]
        extra_kwargs = {
            "id": {"help_text": "Upload task UUID."},
            "status": {"help_text": "Current status: stored, processing, completed, or failed."},
            "filename": {"help_text": "Original uploaded filename."},
            "filesize": {"help_text": "File size in bytes."},
            "sha512": {"help_text": "SHA-512 hash of the uploaded file."},
            "error_message": {"help_text": "Human-readable error description (empty on success)."},
            "error_code": {"help_text": "Machine-readable error code (e.g. PACKAGE_EXISTS)."},
            "result_data": {"help_text": "Parsed package metadata on success (JSON object)."},
            "created_at": {"help_text": "When the upload task was created."},
            "completed_at": {"help_text": "When the upload task finished processing."},
        }


class BuildSerializer(serializers.ModelSerializer):
    """Build record for a repository metadata generation run."""

    repo_uid = serializers.CharField(
        source="repo.repo_uid",
        help_text="Repository this build belongs to.",
    )

    class Meta:
        model = Build
        fields = ["id", "repo_uid", "timestamp", "build_number", "completion_status", "total_duration_sec"]
        extra_kwargs = {
            "id": {"help_text": "Build primary key."},
            "timestamp": {"help_text": "When the build started."},
            "build_number": {"help_text": "Sequential build number within the repository."},
            "completion_status": {"help_text": "Build result: running, success, or error."},
            "total_duration_sec": {"help_text": "Total build duration in seconds."},
        }


class BuildLogSerializer(serializers.ModelSerializer):
    """Individual log line from a build run."""

    build = serializers.SlugRelatedField(
        slug_field="build_number", queryset=Build.objects.all(),
        required=False, allow_null=True,
        help_text="Build number this log line belongs to.",
    )

    class Meta:
        model = BuildLogLine
        fields = [
            "build",
            "timestamp",
            "command",
            "message",
            "loglevel",
            "line_number",
            "execution_time_sec",
            "exec_complete",
        ]
        extra_kwargs = {
            "timestamp": {"help_text": "When the log entry was created."},
            "command": {"help_text": "The command that produced this log line."},
            "message": {"help_text": "Log message content."},
            "loglevel": {"help_text": "Severity level: info, warning, or error."},
            "line_number": {"help_text": "Sequential line number within the build."},
            "execution_time_sec": {"help_text": "Command execution time in seconds."},
            "exec_complete": {"help_text": "Whether the command has finished executing."},
        }
