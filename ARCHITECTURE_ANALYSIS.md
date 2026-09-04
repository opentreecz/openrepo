# OpenRepo Server — Architecture Analysis

> **Date:** 2026-08-31
> **Purpose:** Detailed findings from deep code analysis. Reference for future development.

## API Layer Analysis

### Serializers (12 classes in `web/repo/api/serializers.py`)

| # | Class | Model | Key Fields |
|---|-------|-------|------------|
| 1 | `UserSerializer` | User | href, username, is_superuser, email |
| 2 | `UserDetailSerializer` | User | + api_key (StringRelatedField from auth_token) |
| 3 | `RepoSummarySerializer` | Repository | href_repo, href_packages, repo_uid, repo_type, package_count, last_updated, promote_to |
| 4 | `PGPKeySerializer` | PGPSigningKey | name, email, fingerprint, creation_date. Lookup by fingerprint. |
| 5 | `RepoDetailSerializer` | Repository | + href_upload, signing_key, retention_*, multi_arch, repo_instructions, write_access |
| 6 | `PackageSummarySerializer` | Package | href_package, package_uid, package_name, filename, architecture, upload_date, version |
| 7 | `PackageDetailSerializer` | Package | package_uid, repo_uid, filename, version, architecture, checksum_sha512, build_date, upload_date |
| 8 | `CopySerializer` | (none) | dest_repo_uid (CharField) |
| 9 | `UploadSerializer` | (none) | package_file (FileField) |
| 10 | `UploadTaskSerializer` | UploadTask | id, status, filename, filesize, error_message, result_data (JSON), created_at, completed_at |
| 11 | `BuildSerializer` | Build | repo_uid, timestamp, build_number, completion_status, total_duration_sec |
| 12 | `BuildLogSerializer` | BuildLogLine | build, timestamp, command, message, loglevel, line_number, execution_time_sec, exec_complete |

### Serializer/Response Mismatches (must fix for OpenAPI)

| View | `serializer_class` | Actual Response | Fix |
|------|-------------------|-----------------|-----|
| `UploadViewSet.create()` | `UploadSerializer` | `{"task_id": str}` (manual) | Create `UploadResponseSerializer` |
| `CopyViewSet.create()` | `CopySerializer` | `PackageDetailSerializer` data | `@extend_schema` override |
| `PGPKeysViewSet.create()` | `PGPKeySerializer` | Empty body (201) | `@extend_schema(responses={201: None})` |
| `PGPKeysViewSet.download()` | `PGPKeySerializer` | Raw `HttpResponse` binary | `@extend_schema` for binary |
| `ReposViewSet.create()` | `RepoSummarySerializer` (class-level) | `RepoDetailSerializer` (via `get_serializer_class`) | May need `@extend_schema` |

### Views Returning Manual Responses (not serializer-based)

- `PGPKeysViewSet.create()` — `views.py:112`: empty 201
- `PGPKeysViewSet.destroy()` — `views.py:120-122`: manual `{"detail": "..."}` on 400
- `UploadViewSet.create()` — `views.py:357`: manual `{"task_id": str}` on 202
- `PGPKeysViewSet.download()` — `views.py:131-137`: raw `HttpResponse` binary

### Authentication

- `TokenAuthentication` + `SessionAuthentication` (CSRF enforced for session auth)
- `CustomOpenRepoPermission` at `authentication.py:25-91`:
  - Safe methods: require `is_authenticated`
  - Write on pass-through views: check via string class name comparison (fragile, line 44)
  - All other writes: require `is_superuser`
  - Object-level: superusers always pass; others checked against `Repository.write_access` M2M

### Pagination

- `OpenRepoPagination` extends `PageNumberPagination`
- `page_size_query_param = "page_size"`, `max_page_size = 500`
- Default `PAGE_SIZE = 2000` in settings — exceeds max (DRF only applies max when client sends `page_size`)

### URL Routing

- Router-registered: `users/`, `repos/`, `signingkeys/`, `builds/`, `buildlogs/`
- Manual paths: `whoami`, `upload-status/<uuid>/`, `<repo_uid>/`, `<repo_uid>/packages/`, `<repo_uid>/upload/`, `<repo_uid>/pkg/<pkg_uid>/`, `<repo_uid>/pkg/<pkg_uid>/copy/`
- **Naming collision:** Router generates `repository-detail` for `ReposViewSet`; manual path registers `repo-detail` for `RepoViewSet`

### Upload Flow

1. `POST /api/{repo}/upload/` — accepts multipart `package_file` + optional `overwrite`
2. Creates `UploadTask`, spawns background thread (`upload_processor.py`)
3. Returns `202 Accepted` with `{"task_id": "<uuid>"}`
4. Client polls `GET /api/upload-status/{task_id}/`
5. Background thread: parse package → check duplicates → save → apply retention
6. Terminal states: `completed` (with `result_data`) or `failed` (with `error_message`)

## Security Findings

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| 1 | ~~Shell injection via `shell=True` with architecture field~~ | Critical | ✅ RESOLVED — `shell=False`, argument lists, `RegexValidator` on architecture, 600s timeout |
| 2 | ~~CSRF disabled for session auth~~ | High | ✅ RESOLVED — `CsrfExemptSessionAuthentication` removed, standard `SessionAuthentication` used |
| 3 | ~~Hardcoded fallback SECRET_KEY~~ | High | ✅ RESOLVED — raises `ImproperlyConfigured` if env var not set |
| 4 | ~~`ALLOWED_HOSTS = ["*"]` by default~~ | Medium | ✅ RESOLVED — defaults to `["localhost", "127.0.0.1", DOMAIN_NAME]` |
| 5 | PGP private keys in plaintext DB | Medium | `models.py:33-35` (Phase 4.4) |
| 6 | PGP keys generated without passphrase | Medium | `keyring.py:52` |
| 7 | ~~No upload file size limit~~ | Medium | ✅ RESOLVED — `MAX_UPLOAD_SIZE` setting (default 2 GB) |
| 8 | ~~Upload status lacks per-user authz~~ | Low | ✅ RESOLVED — checks superuser or write access |
| 9 | Weak password validation (min 6, no common check) | Low | `settings.py:155-171` |
| 10 | `repo_uid` validation only at serializer level | Low | `base_repo.py:220` |
| 11 | No filename/metadata sanitization on upload | Low | `views.py:327`, `base_repo.py:89` |
| 12 | Prefix-match directory cleanup | Low | `base_repo.py:150-158` |
| 13 | `tarfile.open()` on untrusted .deb | Low | `fallback_tools.py:83` |

## Adapter Pattern Issues

### File Adapters (`web/adapters/file/`)

- `base_adapter.py` is NOT abstract — methods log warnings and return `None`
- `deb_adapter.py` constructor takes `(filepath)` only — base declares `(filepath, original_filename)`
- `deb_adapter.py:30` accesses private API: `pkg._sections["Package"]`
- `rpm_adapter.py` has leftover commented-out code

### Repo Adapters (`web/adapters/repo/`)

- `base_repo.py:140,148` raises bare `Exception` — should be `NotImplementedError`
- ~~`base_repo.py:184` uses `shell=True`~~ — ✅ RESOLVED: `shell=False` with argument lists
- ~~No subprocess timeout~~ — ✅ RESOLVED: 600-second timeout
- `rpm_repo.py:176-191` duplicates `_copy_packages` logic from base
- `deb_repo.py:51-55` and `deb_repo.py:62-65` compute architecture list independently
- `use_python_tools` checked via env var at call-time — should be constructor-time

### Retention Logic (`web/repo/api/retention.py`)

- N+1 query pattern at lines 42-47
- `keep_latest_n_and_age` uses union (OR) semantics despite name suggesting AND
- No `transaction.atomic()` wrapping — crash leaves partial state
- No DB validation that `retention_keep_count` is set when policy requires it

## Data Model Notes

- `PGPSigningKey.private_key_pem` and `passphrase` — plain `CharField` (no encryption)
- Oversized `max_length=65536` on many fields (filename, package_name, version, etc.)
- No `created_at`/`updated_at` on `Package` — only `upload_date` (manually set)
- `Package.relative_path()` derives disk layout from UID by replacing `-` with `/`
- `promote_to` uses `on_delete=CASCADE` — deleting downstream silently breaks link

## Test Coverage

### What's Tested (20 test files, 100+ methods)

- API CRUD for repos, packages, signing keys, users
- Authentication and permissions (superuser, regular, write_access)
- Retention policies (all 4 types, per-arch, cross-repo protection)
- Upload processing (success, duplicate, overwrite, dedup, cleanup)
- Serializer validation (repo_uid, promote_to circular/duplicate)
- Worker background processing
- File adapters (deb, rpm, generic)
- Management commands
- Signals (staleness on package add/delete)
- Integration: full deb upload + repo generation with real GPG

### What's NOT Tested

- No RPM upload integration test (only deb has full pipeline)
- No E2E tests against openrepo-sync client
- No API pagination test
- No generic repo adapter test
- No concurrent upload test
- No promote workflow API test
- No `_execute_commands` subprocess test
- No `fallback_tools.py` test
- No load/performance tests

## Python CLI Client (`cli/`)

Uses 16 API endpoints (all of them). Hardcoded paths in `rest_interface.py:24-41`.
No URL encoding on parameters. `whoami` is the only endpoint without trailing slash.
Unhandled exceptions: `ORConnectionException` and `ORInvalidRequestException` not
caught in `main.py`.
