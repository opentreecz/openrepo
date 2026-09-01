# OpenRepo — Agent Knowledge Base

## Project Overview

OpenRepo is a web-based package repository management server for hosting Debian
APT (.deb), RPM YUM/DNF (.rpm), and generic file repositories. It provides PGP
signing, retention policies, user access control, a REST API, and a web UI.

- **Backend:** Python 3 / Django 4.2 / Django REST Framework 3.15
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
      authentication.py  — Token auth + CsrfExemptSessionAuthentication
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
    repo/
      base_repo.py       — Base repo adapter (subprocess execution)
      deb_repo.py        — Debian repo metadata generation
      rpm_repo.py        — RPM repo metadata generation
      generic_repo.py    — Generic file repo (minimal)
      fallback_tools.py  — Pure-Python fallbacks (OpenWrt)
    file/
      base_adapter.py    — Base file adapter (NOT abstract — should be)
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

Auth: `Authorization: Token <key>` (DRF TokenAuthentication).

## Known Issues (to fix per DEVELOPMENT_PLAN.md)

### Security (Critical/High)

1. **Shell injection** — `base_repo.py:184` uses `shell=True` with DB-derived values
   (architecture field from uploaded packages). A crafted .deb/.rpm could achieve RCE.

2. **CSRF disabled** — `CsrfExemptSessionAuthentication` at `authentication.py:94-97`
   disables CSRF for all session-authenticated API requests.

3. **Hardcoded SECRET_KEY** — `settings.py:53-57` falls back to an insecure hardcoded
   key when env vars are not set.

4. **PGP keys in plaintext** — `models.py:33-35` stores private keys and passphrases
   as plain `CharField` in the database.

### Architecture

5. **File adapters not abstract** — `base_adapter.py` methods return `None` silently
   instead of using `abc.ABC` + `@abstractmethod`.

6. **Constructor signature mismatch** — `deb_adapter.py` takes `(filepath)` but base
   declares `(filepath, original_filename)` — LSP violation.

7. **No adapter registry** — `if/elif` chains for adapter dispatch.

8. **No subprocess timeout** — `_execute_commands` could hang indefinitely.

9. **Retention N+1 queries** — `retention.py:42-47` runs separate DB query per package.

10. **`keep_latest_n_and_age`** — Name says AND but logic is OR (union semantics).

### API Contract

11. **No OpenAPI spec** — No machine-readable API contract.

12. **No API versioning** — Single unversioned `/api/` path.

13. **Serializer/response mismatches** — 4 views declare wrong `serializer_class`:
    - `UploadViewSet`: declares `UploadSerializer`, returns `{"task_id": str}`
    - `CopyViewSet`: declares `CopySerializer`, returns `PackageDetailSerializer`
    - `PGPKeysViewSet.create()`: returns empty body
    - `PGPKeysViewSet.download()`: returns raw binary

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
