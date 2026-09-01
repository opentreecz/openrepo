# OpenRepo Ecosystem — Comprehensive Development Plan

> **Date:** 2026-08-31
> **Scope:** openrepo (server) + openrepo-sync (client)
> **Approach:** Contract-First (Approach A)
> **License for new code:** AGPL-3.0 in both repos

## Overview

This plan covers 7 workstreams across both repositories, organized into 4 phases.
Each phase builds on the previous one.

**Workstreams:**
1. Shared API contract (OpenAPI)
2. Fragile conflict detection fix
3. Dead abstraction cleanup
4. Code deduplication
5. Security gap fixes
6. Test gap coverage
7. Observability

**Licensing:** All new code in both repos will be AGPL-3.0. Existing openrepo-sync
code (Apache 2.0) remains under Apache 2.0. New files get AGPL-3.0 headers.

**E2E tests:** Each repo will have its own E2E tests that spin up the other as a
Docker dependency.

---

## Phase 1: Foundation — API Contract & Security (Weeks 1–3)

### 1.1 OpenAPI Specification (this repo)

**Goal:** Generate a machine-readable API contract from the existing DRF views.

**Files to change:**

| File | Change |
|------|--------|
| `web/requirements.txt` | Add `drf-spectacular>=0.27` |
| `web/openrepo/settings.py` | Add `drf-spectacular` to `INSTALLED_APPS`, configure `SPECTACULAR_SETTINGS`, set `DEFAULT_SCHEMA_CLASS` |
| `web/openrepo/urls.py` | Add `/api/schema/` (YAML) and `/api/docs/` (Swagger UI) endpoints |
| `web/repo/api/views.py` | Add `@extend_schema()` decorators to fix 4 mismatched views |
| `web/repo/api/serializers.py` | Add `UploadResponseSerializer`, add `@extend_schema_field` for `result_data` |

**View fixes needed:**

| View | Problem | Fix |
|------|---------|-----|
| `UploadViewSet.create()` | `serializer_class = UploadSerializer` but response is `{"task_id": str}` | Create `UploadResponseSerializer`, add `@extend_schema(request=UploadSerializer, responses={202: UploadResponseSerializer})` |
| `CopyViewSet.create()` | `serializer_class = CopySerializer` but response is `PackageDetailSerializer` | Add `@extend_schema(request=CopySerializer, responses={200: PackageDetailSerializer})` |
| `PGPKeysViewSet.create()` | Returns empty 201 body | Add `@extend_schema(responses={201: None})` |
| `PGPKeysViewSet.download()` | Returns raw `HttpResponse` with `application/pgp-keys` | Add `@extend_schema(responses={(200, "application/pgp-keys"): bytes})` |

**New file:** `web/repo/api/schema.py` — Custom `AutoSchema` subclass if needed.

**Validation:** Run `python manage.py spectacular --validate` in CI.

**Known inconsistencies to fix:**
- `UploadSerializer` is declared as `serializer_class` on `UploadViewSet` but never used for deserialization
- `CopySerializer` is declared but response uses `PackageDetailSerializer`
- `PGPKeysViewSet.create()` returns empty body but schema would show `PGPKeySerializer`
- `UploadTask.result_data` is a `JSONField` containing `PackageDetailSerializer` dict — invisible to schema
- `ReposViewSet.get_serializer_class()` returns different serializers for `create` vs `list` — schema generators may pick wrong one
- `PAGE_SIZE=2000` exceeds `max_page_size=500` — default page returns 2000 items
- Browsable API renderer is active (both JSON and HTML)

### 1.2 API Versioning (this repo)

**Goal:** Version the API without breaking existing clients.

**Approach:** URL-prefix versioning with backward-compatible alias.

| File | Change |
|------|--------|
| `web/openrepo/urls.py` | Mount API under both `/api/v1/` and `/api/` (alias) |
| `web/repo/api/views.py` | Add `X-OpenRepo-Version` response header via middleware |

**New file:** `web/repo/api/middleware.py` — `VersionHeaderMiddleware` adding
`X-OpenRepo-Version: 2.5.0` to all API responses.

**No breaking change.** All existing clients continue to work via `/api/`.

### 1.3 Structured Error Responses (this repo)

**Goal:** Replace string-matched error detection with machine-readable error codes.

**New files:**

| File | Purpose |
|------|---------|
| `web/repo/api/errors.py` | Error codes enum: `PACKAGE_EXISTS`, `REPO_NOT_FOUND`, `INVALID_REPO_TYPE`, `KEY_IN_USE`, etc. |
| `web/repo/api/exception_handler.py` | Custom DRF exception handler returning `{"code": "PACKAGE_EXISTS", "detail": "...", "status": 409}` |

**Current error format inconsistencies:**
- DRF `ValidationError`: `{"field_name": ["error msg"]}`
- DRF `NotFound`: `{"detail": "..."}`
- DRF `ParseError`: `{"detail": "..."}`
- Manual error Response: `{"detail": "..."}` (PGP destroy, views.py:120-122)
- `PGPKeysViewSet.destroy()` bypasses exception pipeline (manual Response)

**Key change:** "Package already exists" errors return **HTTP 409 Conflict** (not 400)
with code `PACKAGE_EXISTS`.

### 1.4 Fix Conflict Detection (Client)

**Goal:** Replace string matching with HTTP status code + error code checking.

| File | Change |
|------|--------|
| `openrepo-sync/src/repo_client.rs` | Parse error responses as JSON, extract `code` field |
| `openrepo-sync/src/sync.rs` | Match on typed error variants instead of `e.to_string().contains("400")` |

**New file:** `openrepo-sync/src/errors.rs`

### 1.5 Critical Security Fixes (this repo)

**1.5a — Shell injection fix (Critical)**

| File | Change |
|------|--------|
| `web/adapters/repo/base_repo.py` | Replace `shell=True` with `shell=False`, convert command strings to argument lists |
| `web/adapters/repo/deb_repo.py` | Refactor `_generate_repo_structure()` to build commands as lists |
| `web/adapters/repo/rpm_repo.py` | Same refactor |
| `web/repo/models.py` | Add `RegexValidator` on `architecture` field: `^[a-zA-Z0-9_-]+$` |

**Attack vector:** Architecture field from uploaded package metadata is interpolated
into shell commands. A crafted .deb/.rpm with malicious architecture string could
achieve RCE.

**1.5b — CSRF protection (High)**

| File | Change |
|------|--------|
| `web/repo/api/authentication.py` | Remove `CsrfExemptSessionAuthentication` |
| `frontend/src/http_common.ts` | Add `X-CSRFToken` header from cookie |

**1.5c — SECRET_KEY hardcoding (High)**

| File | Change |
|------|--------|
| `web/openrepo/settings.py` | Remove hardcoded fallback. Raise `ImproperlyConfigured` if no env var. |

**1.5d — ALLOWED_HOSTS (Medium)**

| File | Change |
|------|--------|
| `web/openrepo/settings.py` | Default to `["localhost", "127.0.0.1"]` |

**1.5e — Upload file size limit (Medium)**

| File | Change |
|------|--------|
| `web/repo/api/views.py` | Add `MAX_UPLOAD_SIZE` check, configurable via env var, default 2GB |

**1.5f — Upload status authorization (Low)**

| File | Change |
|------|--------|
| `web/repo/api/views.py` | Verify requesting user has write access to task's repo |

**Additional security findings (lower priority):**
- PGP keys generated without passphrase (`keyring.py:52`)
- Weak password validation (min 6 chars, `CommonPasswordValidator` commented out)
- `repo_uid` validation only at serializer level, not model level
- No filename/metadata sanitization on upload
- Prefix-match directory cleanup could affect similarly-named repos
- `tarfile.open()` on untrusted .deb in fallback tools

---

## Phase 2: Architecture Cleanup (Weeks 3–5)

### 2.1 Implement PackageSource Trait (Client)

Replace dead trait + manual `match` dispatch with proper trait-object dispatch.

### 2.2 Extract Shared GPG Module (Client)

Deduplicate ~200 lines of GPG verification from `deb_repo.rs` and `rpm_repo.rs`
into `src/gpg.rs`.

### 2.3 Share reqwest::Client (Client)

Single HTTP client with shared connection pool. Remove 5 duplicate
`Client::builder()` calls.

### 2.4 Fix Server Adapter Abstractions (this repo)

| File | Change |
|------|--------|
| `web/adapters/file/base_adapter.py` | Convert to `abc.ABC`, use `@abstractmethod`. Fix constructor. |
| `web/adapters/file/deb_adapter.py` | Fix constructor signature to match base class |
| `web/adapters/file/rpm_adapter.py` | Remove commented-out code |
| `web/adapters/repo/base_repo.py` | `NotImplementedError` instead of `Exception`. Add subprocess timeout (600s). |
| `web/adapters/repo/rpm_repo.py` | Merge `_symlink_packages_to_dir` into base class |

**Current issues:**
- `base_adapter.py` is not actually abstract — methods return `None` silently
- `deb_adapter.py` constructor takes `(filepath)` but base declares `(filepath, original_filename)` — LSP violation
- `base_repo.py` raises bare `Exception` instead of `NotImplementedError`
- No subprocess timeout — `createrepo` or `apt-ftparchive` could hang indefinitely
- `_symlink_packages_to_dir` in `rpm_repo.py` duplicates `_copy_packages` from base

### 2.5 Adapter Registry (this repo)

**New file:** `web/adapters/registry.py`

```python
REPO_ADAPTERS = {
    "deb": DebRepoAdapter,
    "rpm": RpmRepoAdapter,
    "files": GenericRepoAdapter,
}
FILE_ADAPTERS = {
    "deb": DebFileAdapter,
    "rpm": RpmFileAdapter,
    "files": GenericFileAdapter,
}
```

### 2.6 Code Deduplication Summary

| Duplication | Strategy | Effort |
|-------------|----------|--------|
| GPG verification (~200 lines, client) | Extract to `src/gpg.rs` | Small |
| `reqwest::Client` (6 places, client) | Pass shared client | Small |
| `_symlink_packages_to_dir` vs `_copy_packages` (server) | Merge into base class | Small |
| Architecture resolution in deb adapter (server) | Extract and reuse | Trivial |
| Test setUp boilerplate (server, 20 files) | Extract shared fixtures module | Medium |
| API URL patterns (Rust + Python clients) | Generate from OpenAPI spec long-term | Medium |

---

## Phase 3: Test Infrastructure (Weeks 5–7)

### 3.1 Typed API Client Structs (Client)

Replace `serde_json::Value` parsing with `PaginatedResponse<T>`, `ApiPackage`, etc.

### 3.2 E2E Tests in Server Repo (this repo)

**New files:**

| File | Purpose |
|------|---------|
| `.github/workflows/e2e-test.yml` | CI workflow |
| `tests/e2e/docker-compose.e2e.yml` | Stack + openrepo-sync service |
| `tests/e2e/config.yaml` | openrepo-sync config |
| `tests/e2e/projects/test-direct-url.yaml` | Test project |
| `tests/e2e/run_e2e.sh` | Test script |

**Test scenarios:**
1. First sync — package uploaded
2. Second sync — "up to date"
3. Conflict handling — `on_conflict: skip`
4. Pruning — upload 3 versions, keep 2
5. API contract — verify response shapes match OpenAPI spec

### 3.3 E2E Tests in Client Repo

New `tests/e2e/` with Rust integration tests behind `#[cfg(feature = "e2e")]`.

### 3.4 Fill Server Test Gaps (this repo)

| Gap | Severity |
|-----|----------|
| No RPM upload integration test | Medium |
| No API pagination test | Medium |
| No generic repo adapter test | Low |
| No concurrent upload test | Low |
| No promote workflow API test | Medium |
| No shared test fixtures | Medium |

### 3.5 Fill Client Test Gaps

| Gap | Severity |
|-----|----------|
| No integration test against real server | High |
| No RPM GPG verification test | Medium |
| No `on_conflict: Overwrite` test | Low |
| No multi-project sync test | Medium |
| No schedule loop test | Medium |

### 3.6 OpenAPI Schema Validation in CI

- Server: `python manage.py spectacular --validate --fail-on-warn`
- Client: Validate typed structs match spec

---

## Phase 4: Observability & Hardening (Weeks 7–9)

### 4.1 Health Check Endpoint (this repo)

`GET /api/health/` — no auth, returns `{"status": "ok", "database": "ok", "worker": "ok|stale|unknown", "version": "2.5.0"}`.

### 4.2 Structured Logging (this repo)

Add `structlog` with JSON output, correlation IDs, request tracing.

### 4.3 Prometheus Metrics (this repo)

Add `django-prometheus` with custom metrics:
- `openrepo_packages_total` (Gauge per repo)
- `openrepo_upload_duration_seconds` (Histogram)
- `openrepo_build_duration_seconds` (Histogram)
- `openrepo_retention_deleted_total` (Counter)

### 4.4 PGP Key Encryption at Rest (this repo)

Fernet encryption for `private_key_pem` and `passphrase` fields.
Data migration to encrypt existing keys.

### 4.5 Rate Limiting (this repo)

DRF throttling: 100 req/min user, 20 req/min upload.

### 4.6 Hash Continuity (Both)

Client sends SHA-256 with upload; server verifies on receipt.
Add `checksum_sha256` field to `Package` model.

### 4.7 Retention Logic Fix (this repo)

- Wrap `apply_retention_policy` in `transaction.atomic()`
- Fix N+1 query with `annotate()` + `Subquery`
- Add DB constraint: `retention_keep_count` required when policy includes `keep_latest_n`
- Note: `keep_latest_n_and_age` uses union semantics (OR), not intersection (AND) — name is misleading

### 4.8 Pagination Fix (this repo)

Change `PAGE_SIZE` from 2000 to 500 to match `max_page_size`.

---

## Execution Order

```
Phase 1 (Weeks 1-3): Foundation
  ├── 1.1 OpenAPI spec generation (server)
  ├── 1.2 API versioning (server)
  ├── 1.3 Structured error responses (server)
  ├── 1.4 Fix conflict detection (client) — depends on 1.3
  └── 1.5 Security fixes (server) — parallel with 1.1-1.4
       ├── 1.5a Shell injection (Critical — do first)
       ├── 1.5b CSRF protection
       ├── 1.5c SECRET_KEY
       ├── 1.5d ALLOWED_HOSTS
       ├── 1.5e Upload size limit
       └── 1.5f Upload status authz

Phase 2 (Weeks 3-5): Architecture
  ├── 2.1 PackageSource trait (client)
  ├── 2.2 GPG module extraction (client)
  ├── 2.3 Shared reqwest::Client (client)
  ├── 2.4 Fix server adapter abstractions (server)
  ├── 2.5 Adapter registry (server)
  └── 2.6 Remaining deduplication (both)

Phase 3 (Weeks 5-7): Testing
  ├── 3.1 Typed API client structs (client) — depends on 1.1
  ├── 3.2 E2E tests in server repo — depends on 1.3
  ├── 3.3 E2E tests in client repo — depends on 1.4, 3.1
  ├── 3.4 Fill server test gaps
  ├── 3.5 Fill client test gaps
  └── 3.6 OpenAPI schema validation in CI — depends on 1.1

Phase 4 (Weeks 7-9): Observability & Hardening
  ├── 4.1 Health check endpoint (server)
  ├── 4.2 Structured logging (server)
  ├── 4.3 Prometheus metrics (server)
  ├── 4.4 PGP key encryption (server)
  ├── 4.5 Rate limiting (server)
  ├── 4.6 Hash continuity (both)
  ├── 4.7 Retention logic fix (server)
  └── 4.8 Pagination fix (server)
```

## File Change Estimate

| Repo | New Files | Modified Files |
|------|-----------|----------------|
| openrepo (server) | ~12 | ~18 |
| openrepo-sync (client) | ~6 | ~12 |

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| API versioning breaks existing clients | `/api/` remains as alias |
| CSRF fix breaks frontend | Update Vue.js Axios config simultaneously |
| SECRET_KEY enforcement breaks deployments | Document migration; provide `generate_secret_key` command |
| `shell=False` refactor may break edge cases | Test with real `apt-ftparchive` and `createrepo_c` |
| E2E tests add CI complexity | Use `workflow_dispatch` initially |
| AGPL-3.0 on openrepo-sync may deter contributors | Clear license boundary documentation |
| `drf-spectacular` may not handle custom views | Manual `@extend_schema` for 4 identified views |
| Fernet encryption requires new env var | Make optional initially, warn if not configured |
