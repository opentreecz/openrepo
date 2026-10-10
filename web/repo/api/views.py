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

import hashlib
import logging
import os
import re

import rest_framework.exceptions
from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import validate_email
from django.db.models.functions import Lower
from django.http import HttpResponse
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from repo.models import Build, BuildLogLine, Package, PGPSigningKey, Repository, UploadTask
from repo.storage.filemanager import RepoFileManager
from repo.storage.keyring import PGPKeyManager

from .errors import ApiErrorCode, api_error
from .filters import BuildFilter, BuildLogFilter
from .serializers import (
    BuildLogSerializer,
    BuildSerializer,
    CopySerializer,
    ErrorResponseSerializer,
    PackageDetailSerializer,
    PackageSummarySerializer,
    PGPKeyCreateRequestSerializer,
    PGPKeySerializer,
    RepoDetailSerializer,
    RepoSummarySerializer,
    UploadResponseSerializer,
    UploadSerializer,
    UploadTaskSerializer,
    UserDetailSerializer,
    UserSerializer,
)
from .retention import apply_retention_policy
from .util import MultipleFieldLookupMixin

logger = logging.getLogger("openrepo_web")


@extend_schema_view(
    list=extend_schema(description="List all user accounts.", tags=["users"]),
    create=extend_schema(description="Create a new user account.", tags=["users"]),
    retrieve=extend_schema(description="Retrieve a user account.", tags=["users"]),
    update=extend_schema(description="Update a user account (full replace).", tags=["users"]),
    partial_update=extend_schema(description="Partially update a user account.", tags=["users"]),
    destroy=extend_schema(description="Delete a user account.", tags=["users"]),
)
class UserViewSet(viewsets.ModelViewSet):
    """Manage user accounts and API keys."""

    queryset = User.objects.all().order_by("-date_joined")
    serializer_class = UserSerializer
    filter_backends = [SearchFilter]
    search_fields = ["username", "email"]


@extend_schema_view(
    list=extend_schema(description="List all repositories.", tags=["repos"]),
    create=extend_schema(description="Create a new repository.", tags=["repos"]),
    retrieve=extend_schema(description="Retrieve a repository summary.", tags=["repos"]),
    update=extend_schema(description="Update a repository (full replace).", tags=["repos"]),
    partial_update=extend_schema(description="Partially update a repository.", tags=["repos"]),
    destroy=extend_schema(description="Delete a repository and all its packages.", tags=["repos"]),
)
class ReposViewSet(viewsets.ModelViewSet):
    """Repository management (list, create, update, delete)."""

    lookup_field = "repo_uid"
    queryset = (
        Repository.objects.all().order_by("repo_uid")
        .select_related("promote_to").prefetch_related("write_access")
    )
    serializer_class = RepoSummarySerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["repo_type"]
    search_fields = ["repo_uid"]
    ordering_fields = ["repo_uid", "last_updated", "package_count"]
    ordering = ["repo_uid"]

    def get_serializer_class(self):
        # On create, we want to provide more details than on the list retrieve
        if self.action == "create":
            return RepoDetailSerializer
        return RepoSummarySerializer

    def perform_create(self, serializer):
        serializer.save()


@extend_schema_view(
    list=extend_schema(description="List all PGP signing keys.", tags=["signing-keys"]),
    retrieve=extend_schema(description="Retrieve a PGP signing key by fingerprint.", tags=["signing-keys"]),
    update=extend_schema(description="Update PGP key metadata.", tags=["signing-keys"]),
    partial_update=extend_schema(description="Partially update PGP key metadata.", tags=["signing-keys"]),
)
class PGPKeysViewSet(viewsets.ModelViewSet):
    """PGP signing key management (generate, list, download, delete)."""

    queryset = PGPSigningKey.objects.all().order_by("-name")
    serializer_class = PGPKeySerializer

    lookup_field = "fingerprint"

    @extend_schema(
        request=PGPKeyCreateRequestSerializer,
        responses={201: None},
        description="Generate a new PGP signing key pair.",
        tags=["signing-keys"],
    )
    def create(self, request, *args, **kwargs):

        full_name = request.POST.get("name")
        email = request.POST.get("email")

        if len(full_name) < 1 or len(full_name) > 1024:
            raise rest_framework.exceptions.ValidationError({"name": "Invalid name"})

        try:
            validate_email(email)
        except Exception:
            raise rest_framework.exceptions.ValidationError({"email": "Invalid e-mail address"})

        keyring = PGPKeyManager()
        keyring.generate_key(full_name, email)

        return Response(status=rest_framework.status.HTTP_201_CREATED)

    @extend_schema(
        responses={204: None, 409: ErrorResponseSerializer},
        description="Delete a PGP signing key. Returns 409 if the key is in use by a repository.",
        tags=["signing-keys"],
    )
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        referencing_repos = Repository.objects.filter(signing_key=instance)
        if len(referencing_repos) > 0:
            repos = [repo.repo_uid for repo in referencing_repos]
            return api_error(
                ApiErrorCode.KEY_IN_USE,
                "Unable to delete. You must first remove this key from repos: " + ", ".join(repos),
                rest_framework.status.HTTP_409_CONFLICT,
            )

        keyring = PGPKeyManager()
        keyring.delete(instance.fingerprint, passphrase=instance.passphrase)

        self.perform_destroy(instance)
        return Response(status=rest_framework.status.HTTP_204_NO_CONTENT)

    @extend_schema(
        responses={(200, "application/pgp-keys"): OpenApiTypes.BINARY},
        description="Download the public PGP key in ASCII-armored format.",
        tags=["signing-keys"],
    )
    @action(detail=True, methods=["get"])
    def download(self, request, fingerprint=None):
        key = self.get_object()
        filename = f"{key.fingerprint[-16:]}.asc"
        response = HttpResponse(key.public_key_pem, content_type="application/pgp-keys")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


@extend_schema_view(
    retrieve=extend_schema(description="Retrieve the currently authenticated user's account and API key.", tags=["auth"]),
)
class WhoAmIViewSet(rest_framework.mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Returns the authenticated user's profile and API token."""
    serializer_class = UserDetailSerializer

    def get_object(self):
        return self.request.user


@extend_schema_view(
    retrieve=extend_schema(description="Retrieve full repository detail and configuration.", tags=["repos"]),
    update=extend_schema(description="Update repository configuration (full replace).", tags=["repos"]),
    partial_update=extend_schema(description="Partially update repository configuration.", tags=["repos"]),
    destroy=extend_schema(description="Delete a repository and all its packages.", tags=["repos"]),
)
class RepoViewSet(viewsets.ModelViewSet):
    """Single repository detail, update, and delete."""

    lookup_field = "repo_uid"
    queryset = Repository.objects.all()
    serializer_class = RepoDetailSerializer

    def perform_update(self, serializer):
        original_object = self.get_object()
        changes = serializer.validated_data
        instance = serializer.save()

        # If they update the PGP key, mark the repo as stale so it's regenerated
        if original_object.signing_key != changes.get("signing_key"):
            logger.debug("PGP key changed, marking repo as stale")
            instance.is_stale = True
            instance.save()


@extend_schema_view(
    list=extend_schema(
        description="List packages in a repository. Supports filtering, search, and ordering.",
        tags=["packages"],
        parameters=[
            OpenApiParameter("repo_uid", str, OpenApiParameter.PATH, description="Repository identifier."),
        ],
    ),
)
class PackagesViewSet(viewsets.ModelViewSet):
    """Package listing with filtering, search, and ordering."""

    lookup_field = "repo__repo_uid"
    queryset = Package.objects.all()
    serializer_class = PackageSummarySerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        "package_name": ["exact", "icontains"],
        "version": ["exact"],
        "architecture": ["exact"],
        "filename": ["icontains"],
        "checksum_sha512": ["exact"],
    }
    search_fields = ["package_name", "filename", "version", "architecture"]
    ordering_fields = ["package_name", "version", "architecture", "upload_date", "filename"]
    ordering = ["-upload_date"]

    def get_queryset(self):
        repo_uid = self.kwargs["repo_uid"]
        if not Repository.objects.filter(repo_uid=repo_uid).exists():
            raise rest_framework.exceptions.NotFound(f"Repo {repo_uid} not found")
        return Package.objects.filter(repo__repo_uid=repo_uid).select_related("repo")

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        ordering = self.request.query_params.get("ordering")
        if ordering:
            parts = ordering.split(",")
            new_parts = []
            for part in parts:
                if part.lstrip("-") == "package_name":
                    if part.startswith("-"):
                        new_parts.append(Lower("package_name").desc())
                    else:
                        new_parts.append(Lower("package_name").asc())
                else:
                    new_parts.append(part)
            if new_parts:
                queryset = queryset.order_by(*new_parts)
        return queryset


@extend_schema_view(
    retrieve=extend_schema(description="Retrieve full package detail.", tags=["packages"]),
    update=extend_schema(description="Update package metadata (full replace).", tags=["packages"]),
    partial_update=extend_schema(description="Partially update package metadata.", tags=["packages"]),
    destroy=extend_schema(description="Delete a package from the repository.", tags=["packages"]),
)
class PackageViewSet(MultipleFieldLookupMixin, viewsets.ModelViewSet):
    """Single package detail, update, and delete."""

    lookup_fields = ("repo__repo_uid", "package_uid")
    queryset = Package.objects.all()
    serializer_class = PackageDetailSerializer


@extend_schema_view(
    list=extend_schema(description="List repository builds. Supports filtering by repo, build number, and time range.", tags=["builds"]),
)
class BuildViewSet(rest_framework.mixins.ListModelMixin, viewsets.GenericViewSet):
    """Build history for repository metadata generation."""

    queryset = Build.objects.all().order_by("-build_number").select_related("repo")
    serializer_class = BuildSerializer

    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = BuildFilter
    ordering_fields = ["build_number", "timestamp", "total_duration_sec"]
    ordering = ["-build_number"]


@extend_schema_view(
    list=extend_schema(description="List build log lines. Supports filtering by build, repo, log level, and time range.", tags=["builds"]),
)
class BuildLogViewSet(rest_framework.mixins.ListModelMixin, viewsets.GenericViewSet):
    """Build log lines from repository metadata generation runs."""

    queryset = BuildLogLine.objects.all().select_related("build")
    serializer_class = BuildLogSerializer

    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = BuildLogFilter
    ordering_fields = ["line_number", "timestamp"]
    ordering = ["line_number"]


class CopyViewSet(viewsets.ViewSet):
    serializer_class = CopySerializer

    @extend_schema(
        request=CopySerializer,
        responses={200: PackageDetailSerializer, 409: ErrorResponseSerializer},
        description="Copy a package to another repository.",
        tags=["packages"],
    )
    def create(self, request, repo_uid, package_uid):
        try:
            src_repo = Repository.objects.get(repo_uid=repo_uid)
        except Repository.DoesNotExist:
            raise rest_framework.exceptions.NotFound(f"Source repo_uid {repo_uid} not found")

        try:
            package = Package.objects.get(repo=src_repo, package_uid=package_uid)
        except Package.DoesNotExist:
            raise rest_framework.exceptions.NotFound(f"Package {package_uid} not found in repo {repo_uid}")

        dst_repo_uid = request.data.get("dest_repo_uid")
        logger.debug(request.data)
        logger.debug(f"Copying {repo_uid} / {package_uid} to {dst_repo_uid}")

        try:
            dst_repo = Repository.objects.get(repo_uid=dst_repo_uid)
        except Repository.DoesNotExist:
            raise rest_framework.exceptions.NotFound(f"Destination repo_uid {dst_repo_uid} not found")

        # Since DRF does not know that this "copy" is associated with a repo, we have to tell it explicitly
        # to check object permissions
        self.check_object_permissions(request, dst_repo)

        # Make sure destination repo is either the same type or is generic
        if dst_repo.repo_type != "files" and dst_repo.repo_type != src_repo.repo_type:
            raise rest_framework.exceptions.ParseError(
                f"Incompatible destination repository.  Source repo is {src_repo.repo_type} "
                f"destination repo is {dst_repo.repo_type}"
            )

        # For generic repo, we always want to refer to the file by filename, not parsed package name
        if dst_repo.repo_type == "files":
            package.package_name = package.filename

        if Package.objects.filter(
            repo=dst_repo,
            package_name=package.package_name,
            version=package.version,
            architecture=package.architecture,
        ).count() > 0:
            return api_error(
                ApiErrorCode.PACKAGE_EXISTS,
                f"Package {package.package_name} v{package.version} ({package.architecture}) "
                f"already exists in destination repo {dst_repo}",
                rest_framework.status.HTTP_409_CONFLICT,
            )

        if Package.objects.filter(repo=dst_repo, package_uid=package.package_uid):
            return api_error(
                ApiErrorCode.PACKAGE_EXISTS,
                f"An identical package already exists in the destination repo {package.package_uid}",
                rest_framework.status.HTTP_409_CONFLICT,
            )

        # Set "pk" to none in order to make the save create a new model
        # Thus copying it from one to another
        package.pk = None
        package.repo = dst_repo
        package.save()

        apply_retention_policy(dst_repo, package.package_name, package.architecture)

        serializer = PackageDetailSerializer(package)
        return Response(serializer.data)


class UploadViewSet(viewsets.ViewSet):
    serializer_class = UploadSerializer

    @extend_schema(
        request={"multipart/form-data": UploadSerializer},
        responses={202: UploadResponseSerializer, 409: ErrorResponseSerializer},
        description=(
            "Upload a package file. Returns a task ID for async status polling. "
            "Returns 409 if the package already exists and overwrite is not set."
        ),
        tags=["upload"],
    )
    def create(self, request, repo_uid):
        try:
            repo = Repository.objects.get(repo_uid=repo_uid)
        except Repository.DoesNotExist:
            raise rest_framework.exceptions.NotFound(f"Repo {repo_uid} not found")

        self.check_object_permissions(request, repo)

        file_uploaded = request.FILES.get("package_file")
        if file_uploaded is None:
            raise rest_framework.exceptions.ValidationError({"package_file": "This field is required."})

        if file_uploaded.size > settings.MAX_UPLOAD_SIZE:
            raise rest_framework.exceptions.ValidationError(
                {"package_file": f"File size {file_uploaded.size} bytes exceeds the maximum "
                 f"allowed size of {settings.MAX_UPLOAD_SIZE} bytes."}
            )

        overwrite_str = request.POST.get("overwrite", "0").lower()
        overwrite = overwrite_str in ("true", "1", "yes")
        filesize = file_uploaded.size
        filename = os.path.basename(file_uploaded.name)
        if not filename or re.search(r'[\x00-\x1f]', filename):
            raise rest_framework.exceptions.ValidationError(
                {"package_file": "Invalid filename."}
            )

        file_manager = RepoFileManager()
        stored_filename = file_manager.get_filepath()
        full_stored_filepath = os.path.join(settings.STORAGE_PATH, stored_filename)

        os.makedirs(os.path.dirname(full_stored_filepath), exist_ok=True)

        sha512_hash = hashlib.sha512()
        with open(full_stored_filepath, "wb") as outf:
            logger.debug(f"Writing file to {full_stored_filepath}")
            for chunk in file_uploaded.chunks():
                outf.write(chunk)
                sha512_hash.update(chunk)

        sha512 = sha512_hash.hexdigest()

        task = UploadTask.objects.create(
            repo=repo,
            status="stored",
            filename=filename,
            filesize=filesize,
            overwrite=overwrite,
            stored_path=full_stored_filepath,
            sha512=sha512,
        )

        from repo.tasks import process_upload_task
        process_upload_task.delay(str(task.pk))

        return Response({"task_id": str(task.pk)}, status=rest_framework.status.HTTP_202_ACCEPTED)


@extend_schema_view(
    retrieve=extend_schema(
        description="Poll the status of an asynchronous upload task. Returns 404 if the task does not exist or the user lacks access.",
        tags=["upload"],
    ),
)
class UploadStatusView(viewsets.ViewSet):
    """Upload task status polling endpoint."""
    serializer_class = UploadTaskSerializer

    def retrieve(self, request, task_id):
        try:
            task = UploadTask.objects.get(pk=task_id)
        except UploadTask.DoesNotExist:
            raise rest_framework.exceptions.NotFound("Upload task not found")

        # Authorization: user must be superuser or have write access to the task's repo.
        # Return 404 (not 403) to avoid leaking task existence.
        if not request.user.is_superuser:
            if not Repository.objects.filter(pk=task.repo_id, write_access=request.user).exists():
                raise rest_framework.exceptions.NotFound("Upload task not found")

        serializer = UploadTaskSerializer(task, context={"request": request})
        return Response(serializer.data)


class HealthCheckView(viewsets.ViewSet):
    """
    Unauthenticated health check endpoint.

    Returns database connectivity status and the application version.
    Intended for monitoring systems and load balancer probes.
    """

    authentication_classes = []
    permission_classes = []

    @extend_schema(
        responses={200: {
            "type": "object",
            "properties": {
                "status": {"type": "string", "example": "ok"},
                "database": {"type": "string", "example": "ok"},
                "version": {"type": "string", "example": "2.5.0"},
                "repos": {"type": "integer", "example": 5},
                "packages": {"type": "integer", "example": 142},
            },
        }},
    )
    def retrieve(self, request):
        from django.db import connection

        db_status = "ok"
        try:
            connection.ensure_connection()
        except Exception:
            db_status = "unavailable"

        version = getattr(settings, "SPECTACULAR_SETTINGS", {}).get("VERSION", "unknown")

        return Response({
            "status": "ok" if db_status == "ok" else "degraded",
            "database": db_status,
            "version": version,
            "repos": Repository.objects.count(),
            "packages": Package.objects.count(),
        })
