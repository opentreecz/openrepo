---
layout: default
title: Development
nav_order: 6
---

<p align="center">
  <img src="https://raw.githubusercontent.com/opentreecz/.github/master/profile/img/opentreeczlogo.jpeg" alt="opentree.cz" width="120"/>
</p>

# Development
{: .no_toc }

<details open markdown="block">
  <summary>Contents</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

## Architecture

OpenRepo consists of four processes:

| Process | Role |
|---|---|
| **Nginx** | Serves static files, Vue frontend, and repo files; proxies `/api/` and `/admin/` to Django |
| **Django app server** | Hosts the REST API and Django admin interface |
| **Django worker** | Regenerates repo metadata when packages change; runs nightly retention sweeps |
| **PostgreSQL** | Primary data store (SQLite supported for development) |

**Tech stack:**

| Layer | Technology |
|---|---|
| Backend | Python 3, Django 4.2, Django REST Framework |
| Frontend | Vue 3, Vuetify, Vite, TypeScript |
| Package tools | `apt-ftparchive` (deb), `createrepo_c` (rpm), `python-gnupg` |
| Database | PostgreSQL (production), SQLite (development) |
| Container | Docker, Nginx |

---

## Dev environment setup

**1. Create `web/openrepo/settings_local.py`:**

```python
import os

os.environ["OPENREPO_VAR_DIR"] = "/var/tmp/openrepo/"
os.environ["OPENREPO_DEBUG"] = "TRUE"
os.environ["OPENREPO_DB_TYPE"] = "sqlite"
os.environ["OPENREPO_LOGLEVEL"] = "DEBUG"
```

**2. Install system dependencies:**

```bash
sudo apt-get install -y createrepo-c gpg libapt-pkg-dev libpq-dev python3-dev
```

**3. Install Python dependencies:**

```bash
pip install -r web/requirements.txt
pip install -r web/dev-requirements.txt   # flake8, coverage
```

**4. Run each process in a separate terminal:**

```bash
# Django dev server
cd web && ./manage.py migrate && ./manage.py runserver

# Background worker
cd web && ./manage.py runworker

# Vue dev server (hot reload)
cd frontend && npm install && npm run dev

# Nginx dev proxy
nginx -c /path/to/openrepo/deploy/nginx/nginx.conf.dev
```

Navigate to **http://localhost:5173/** — both servers support live reload.

---

## Running tests

```bash
OPENREPO_VAR_DIR=/tmp/openrepo python3 web/manage.py test repo.tests
```

208 tests total, 1 skipped (RPM integration — requires a real RPM file on disk).

**Run a specific test module:**
```bash
OPENREPO_VAR_DIR=/tmp/openrepo python3 web/manage.py test repo.tests.test_retention
```

See [web/CODE_COVERAGE.md](https://github.com/opentreecz/openrepo/blob/main/web/CODE_COVERAGE.md) for coverage instructions.

---

## Linting

```bash
# Python — from repo root
flake8 .

# Frontend
cd frontend && npm run lint

# Frontend type check (non-blocking)
cd frontend && npm run type-check
```

---

## Management commands

| Command | Description |
|---|---|
| `./manage.py runworker` | Start the background worker |
| `./manage.py startup_checks` | Run at app startup — syncs DB keys into the local GPG keyring |
| `./manage.py refresh_keychain` | Re-import all PGP keys from DB into the local GPG keyring |
| `./manage.py import_pgp_private_key <path> [--passphrase <p>]` | Import an existing PGP key from PEM file |
| `./manage.py migrate` | Apply database migrations |
| `./manage.py createsuperuser` | Create a new admin user |

---

## CI/CD workflows

| Workflow | File | Triggers |
|---|---|---|
| **CI** (Django + CLI tests) | `.github/workflows/main.yml` | push, pull_request, weekly |
| **Lint** (flake8 + ESLint) | `.github/workflows/lint.yml` | push, pull_request |
| **Docker build & push** | `.github/workflows/docker-build.yml` | push to `main`, version tags, weekly |
| **GitHub Pages** | `.github/workflows/pages.yml` | push to `main` |

Docker images are pushed to `ghcr.io/opentreecz/openrepo:latest`. Weekly scheduled runs rebuild against the latest base images so security patches land automatically.

---

## Contributing

This fork tracks [openkilt/openrepo](https://github.com/openkilt/openrepo) upstream. A local `openkilt-master` branch mirrors upstream `master` for safe comparison:

```bash
git fetch upstream
git checkout openkilt-master
git merge upstream/master

# See what upstream has that main doesn't
git log --oneline main..openkilt-master
```

To propose changes back upstream, branch from `openkilt-master` and open a PR against `openkilt/openrepo`.
