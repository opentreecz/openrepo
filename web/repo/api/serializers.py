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

    class Meta:
        model = User
        fields = ["href", "username", "is_superuser", "email"]


class UserDetailSerializer(serializers.HyperlinkedModelSerializer):
    api_key = serializers.StringRelatedField(source="auth_token", read_only=True, many=False)

    class Meta:
        model = User
        fields = ["href", "username", "is_superuser", "email", "api_key"]


class RepoSummarySerializer(serializers.HyperlinkedModelSerializer):
    href_repo = ParameterisedHyperlinkedIdentityField(
        view_name="repo-detail", lookup_fields=([("repo_uid", "repo_uid")]), read_only=True
    )
    href_packages = ParameterisedHyperlinkedIdentityField(
        view_name="package-list", lookup_fields=([("repo_uid", "repo_uid")]), read_only=True
    )
    promote_to = serializers.SlugRelatedField(slug_field="repo_uid", read_only=True, allow_null=True)

    class Meta:
        model = Repository
        fields = [
            "href_repo",
            "href_packages",
            "repo_uid",
            "repo_type",
            "package_count",
            "last_updated",
            "promote_to",
        ]


class PGPKeySerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = PGPSigningKey
        lookup_field = "fingerprint"
        extra_kwargs = {"href": {"lookup_field": "fingerprint"}}
        fields = ["name", "email", "fingerprint", "creation_date", "href"]
        read_only_fields = ["creation_date"]


class RepoDetailSerializer(serializers.HyperlinkedModelSerializer):
    href_packages = ParameterisedHyperlinkedIdentityField(
        view_name="package-list", lookup_fields=([("repo_uid", "repo_uid")]), read_only=True
    )
    href_upload = ParameterisedHyperlinkedIdentityField(
        view_name="upload", lookup_fields=([("repo_uid", "repo_uid")]), read_only=True
    )

    signing_key = serializers.SlugRelatedField(
        slug_field="fingerprint", queryset=PGPSigningKey.objects.all(), read_only=False, required=False, allow_null=True
    )
    promote_to = serializers.SlugRelatedField(
        slug_field="repo_uid", queryset=Repository.objects.all(), read_only=False, required=False, allow_null=True
    )

    write_access = serializers.StringRelatedField(read_only=True, many=True)

    repo_instructions = serializers.SerializerMethodField()

    class Meta:
        model = Repository
        fields = [
            "href_packages",
            "href_upload",
            "repo_uid",
            "repo_type",
            "package_count",
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

    def get_repo_instructions(self, obj):
        repo_adapter = get_repo_adapter(obj)
        return repo_adapter._get_repo_instructions()

    def validate(self, attrs):
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
    href_package = ParameterisedHyperlinkedIdentityField(
        view_name="package-detail",
        lookup_fields=([("repo.repo_uid", "repo_uid"), ("package_uid", "package_uid")]),
        read_only=True,
    )

    class Meta:
        model = Package
        fields = ["href_package", "package_uid", "package_name", "filename", "architecture", "upload_date", "version"]


class PackageDetailSerializer(serializers.HyperlinkedModelSerializer):
    repo_uid = serializers.StringRelatedField(source="repo", read_only=True)

    class Meta:
        model = Package
        fields = [
            "package_uid",
            "repo_uid",
            "filename",
            "version",
            "architecture",
            "checksum_sha512",
            "build_date",
            "upload_date",
        ]


class CopySerializer(serializers.Serializer):
    dest_repo_uid = serializers.CharField()

    class Meta:
        fields = ["dest_repo_uid"]


class UploadSerializer(serializers.Serializer):
    package_file = serializers.FileField()
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

    class Meta:
        model = UploadTask
        fields = [
            "id",
            "status",
            "filename",
            "filesize",
            "error_message",
            "error_code",
            "result_data",
            "created_at",
            "completed_at",
        ]


class BuildSerializer(serializers.ModelSerializer):
    repo_uid = serializers.CharField(source="repo.repo_uid")

    class Meta:
        model = Build
        fields = ["repo_uid", "timestamp", "build_number", "completion_status", "total_duration_sec"]


class BuildLogSerializer(serializers.ModelSerializer):
    build = serializers.SlugRelatedField(
        slug_field="build_number", queryset=Build.objects.all(), required=False, allow_null=True
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
