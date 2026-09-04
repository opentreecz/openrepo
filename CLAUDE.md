# OpenRepo — Agent Knowledge Base

## Project Overview

OpenRepo is a web-based package repository management server for hosting Debian
APT (.deb), RPM YUM/DNF (.rpm), and generic file repositories. It provides PGP
signing, retention policies, user access control, a REST API, and a web UI.

- **Backend:** Python 3 / Django 4.2 / Django REST Framework 3.15 / drf-spectacular (OpenAPI 3.0)
- **Frontend:** Vue.js 3 + TypeScript + Vuetify 3 + Vite
- **Database:** PostgreSQL 16 (production) or SQLite (development)
- **Web server:** Nginx (reverse proxy)
- **Version:** 2.4.2
- **License:** AGPL-3.0
- **CI coverage threshold:** 85%

## Architecture

```
web/
  openrepo/
    settings.py          — Django settings
    urls.py              — Root URL config
  repo/
    models.py            — Repository, Package, PGPSigningKey, Build, UploadTask
    views.py             — Web views
    signals.py           — Package add/delete signals (mark repo stale)
    api/
      views.py           — DRF viewsets (14 endpoint groups)
      urls.py            — API URL routing
      serializers.py     — 12 serializer classes
      upload_processor.py — Async upload handling (background thread)
      retention.py       — Package retention policy logic
      authentication.py  — Token auth + permissions
      middleware.py      — VersionHeaderMiddleware (X-OpenRepo-Version)
      pagination.py      — PageNumberPagination (max 500)
      filters.py         — Build/BuildLog filters
      util.py            — Custom hyperlinked fields, SHA-512
    worker/
      bgworker.py        — Background thread for repo rebuilds + retention
    storage/
      keyring.py         — GPG keyring management
      filemanager.py     — File storage with deduplication
    tests/               — 20 test files, 100+ test methods
  adapters/
    registry.py          — Adapter registry (REPO_ADAPTERS, FILE_ADAPTERS dicts)
    repo/
      base_repo.py       — Base repo adapter (subprocess execution, shell=False)
      deb_repo.py        — Debian repo metadata generation
      rpm_repo.py        — RPM repo metadata generation
      generic_repo.py    — Generic file repo (minimal)
      fallback_tools.py  — Pure-Python fallbacks (OpenWrt)
    file/
      base_adapter.py    — Abstract base file adapter (abc.ABC)
      deb_adapter.py     — .deb metadata parsing
      rpm_adapter.py     — .rpm metadata parsing
      file_adapter.py    — Generic file handling
frontend/
  src/                   — Vue.js 3 SPA
cli/
  main.py                — Python CLI client
  openrepo_cli/
    rest_interface.py    — REST API wrapper (16 endpoints)
```

## API Endpoints (14 groups)

| # | Endpoint | Methods | Used by sync client? |
|---|----------|---------|---------------------|
| 1 | `/api/whoami` | GET | Yes |
| 2 | `/api/repos/` | GET, POST | No |
| 3 | `/api/users/` | CRUD | No |
| 4 | `/api/signingkeys/` | CRUD + download | No |
| 5 | `/api/{repo_uid}/` | GET, PUT, DELETE | No |
| 6 | `/api/{repo_uid}/packages/` | GET | Yes |
| 7 | `/api/{repo_uid}/upload/` | POST | Yes |
| 8 | `/api/{repo_uid}/pkg/{pkg_uid}/` | GET, PUT, DELETE | Yes (DELETE only) |
| 9 | `/api/{repo_uid}/pkg/{pkg_uid}/copy/` | POST | No |
| 10 | `/api/upload-status/{task_id}/` | GET | Yes |
| 11 | `/api/builds/` | GET | No |
| 12 | `/api/buildlogs/` | GET | No |
| 13 | `/api/schema/` | GET | No (public) |
| 14 | `/api/docs/` | GET | No (public) |

Auth: `Authorization: Token <key>` (DRF TokenAuthentication).

## Known Issues (to fix per DEVELOPMENT_PLAN.md)

### Security (Critical/High)

1. **~~Shell injection~~** — ✅ RESOLVED: `base_repo.py` now uses `shell=False` with
   argument lists. Architecture field has `RegexValidator`. Subprocess timeout (600s) added.

2. **~~CSRF disabled~~** — ✅ RESOLVED: `CsrfExemptSessionAuthentication` removed.
   Standard `SessionAuthentication` with CSRF enforcement. Frontend sends `X-CSRFToken`.

3. **~~Hardcoded SECRET_KEY~~** — ✅ RESOLVED: Raises `ImproperlyConfigured` if
   `OPENREPO_SECRET_KEY` or `DJANGO_SECRET_KEY` env var is not set.

4. **PGP keys in plaintext** — `models.py:33-35` stores private keys and passphrases
   as plain `CharField` in the database. (Phase 4.4)

### Security (Medium/Low — resolved)

- **~~ALLOWED_HOSTS = ["*"]~~** — ✅ RESOLVED: Defaults to `["localhost", "127.0.0.1", DOMAIN_NAME]`.
  Use `OPENREPO_ALLOWED_HOSTS` env var for additional hosts.
- **~~No upload file size limit~~** — ✅ RESOLVED: `MAX_UPLOAD_SIZE` setting (default 2 GB),
  configurable via `OPENREPO_MAX_UPLOAD_SIZE` env var.
- **~~Upload status lacks per-user authz~~** — ✅ RESOLVED: `UploadStatusView` checks
  superuser or write access to the task's repo.

### Architecture

5. **~~File adapters not abstract~~** — ✅ RESOLVED: `base_adapter.py` converted to
   `abc.ABC` with `@abstractmethod`. All subclasses call `super().__init__()`.

6. **~~Constructor signature mismatch~~** — ✅ RESOLVED: All file adapter constructors
   now accept `(filepath, original_filename=None)` matching the base class.

7. **~~No adapter registry~~** — ✅ RESOLVED: `adapters/registry.py` provides
   `REPO_ADAPTERS` and `FILE_ADAPTERS` dicts. Factory functions use registry lookup.

8. **~~No subprocess timeout~~** — ✅ RESOLVED: 600-second timeout on all subprocess calls.

9. **Retention N+1 queries** — `retention.py:42-47` runs separate DB query per package.

10. **`keep_latest_n_and_age`** — Name says AND but logic is OR (union semantics).

### API Contract

11. **~~No OpenAPI spec~~** — ✅ RESOLVED: `drf-spectacular` added, schema at `/api/schema/`, Swagger UI at `/api/docs/`

12. **~~No API versioning~~** — ✅ RESOLVED: API available at both `/api/v1/` (versioned)
    and `/api/` (backward-compatible alias). `X-OpenRepo-Version` header on all API responses.

13. **~~Serializer/response mismatches~~** — ✅ RESOLVED: `@extend_schema` decorators added to fix:
    - `UploadViewSet`: `UploadResponseSerializer` for 202 response
    - `CopyViewSet`: `PackageDetailSerializer` for response
    - `PGPKeysViewSet.create()`: `PGPKeyCreateRequestSerializer` for request, empty 201 response
    - `PGPKeysViewSet.download()`: binary response annotation

14. **PAGE_SIZE=2000 > max_page_size=500** — Default page exceeds max.

### Testing

15. **No E2E tests** — No test exercises openrepo-sync against a running server.
16. **No RPM upload integration test** — Only deb has full pipeline test.
17. **No pagination test** — `?page=2` behavior untested.
18. **No generic repo test** — `generic_repo.py` entirely untested.

## Build & Test Commands

```bash
# Backend tests
cd web && python manage.py test repo.tests --verbosity=2

# Coverage
cd web && coverage run manage.py test repo.tests && coverage report --fail-under=85

# Lint
flake8 web/

# Frontend
cd frontend && npm run build
cd frontend && npx eslint src/

# CLI tests
cd cli && python -m pytest tests/

# Docker
docker compose up -d
```

## Database Models (5 main)

- `Repository` — repo_uid, type (deb/rpm/files), signing_key, retention, multi_arch
- `Package` — package_uid, filename, package_name, architecture, version, checksum_sha512
- `PGPSigningKey` — name, email, fingerprint, private_key_pem, passphrase
- `Build` — repo, build_number, status, duration
- `UploadTask` — status, stored_path, sha512, result_data (JSON)

## Related Repository

- **openrepo-sync client:** `../openrepo-sync/` (or `github.com/opentreecz/openrepo-sync`)
- See `../openrepo-sync/DEVELOPMENT_PLAN.md` for client-side changes
