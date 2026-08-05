# openrepo

OpenRepo is a web-based server for managing and hosting repositories containing Debian apt/deb, Red Hat rpm, and generic package files.

The server supports:

  - RPM, Deb, and Generic repository generation and hosting compatible with Debian/Ubuntu `apt-get` and Red Hat `yum`/`dnf` tools
  - **Multi-architecture Debian repositories** — generate per-architecture `binary-amd64/`, `binary-arm64/`, etc. instead of the legacy `binary-any/` layout
  - Package upload, deletion, copying, and promotion (e.g., for moving packages through dev → QA → beta → production repos)
  - **Package retention policies** — automatically prune old package versions by count, age, or both
  - PGP signing key creation and management
  - User read/write access control per repository
  - REST API and CLI for CI/CD integration
  - Async drag-and-drop package upload with real-time status tracking
  - Dark/light theme toggle


![OpenRepo Demo Video](https://github.com/openkilt/openrepo/blob/master/util/doc_images/openrepo-demo.gif?raw=true)

## Getting Started

The preferred method for running OpenRepo is with Docker using the provided `docker-compose.yml`.  This starts all required services and a PostgreSQL database.  All persistent data (database, cache, PGP keys, and package files) is stored in a named Docker volume.

**Prerequisites:** [Docker](https://docs.docker.com/engine/install/) and the [Docker Compose plugin](https://docker-docs.netlify.app/compose/install/).

```bash
wget https://raw.githubusercontent.com/opentreecz/openrepo/main/docker-compose.yml
docker compose up -d
```

Navigate to http://localhost:7376

Default credentials:

    username: admin
    password: admin

> **Security:** Change the default admin password immediately after first login.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `OPENREPO_SECRET_KEY` | *(insecure built-in)* | Django secret key — set this in production. `DJANGO_SECRET_KEY` is also accepted for compatibility. |
| `OPENREPO_PG_PASSWORD` | `postgres` | PostgreSQL password |
| `OPENREPO_PG_HOSTNAME` | `db` | PostgreSQL host |
| `OPENREPO_PG_DATABASE` | `openrepo` | PostgreSQL database name |
| `OPENREPO_PG_USERNAME` | `postgres` | PostgreSQL username |
| `OPENREPO_DB_TYPE` | `sqlite` | Database backend: `sqlite` or `postgresql` |
| `OPENREPO_VAR_DIR` | `/var/lib/openrepo/` | Base directory for all persistent data |
| `OPENREPO_DEBUG` | `FALSE` | Enable Django debug mode |
| `OPENREPO_LOGLEVEL` | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `OPENREPO_DOMAIN` | `localhost:8080` | Public domain name (used in repo instructions) |
| `OPENREPO_SECURE_HOSTS` | `FALSE` | Set `TRUE` to restrict `ALLOWED_HOSTS` to `localhost` and `OPENREPO_DOMAIN` only |
| `OPENREPO_CSRF_TRUSTED_ORIGINS` | *(none)* | Space-separated list of trusted CSRF origins for reverse proxies |
| `RPM_VERSION_IGNORE_BUILD_NUM` | `false` | Set `true` to use only the RPM `version` field and ignore the `release` (build number) suffix |

Copy `.env.example` to `.env` and fill in values before starting.


## CI Integration

A common requirement is to automatically upload packages produced by Continuous Integration.  See the [CLI documentation](cli/) for details.

The CLI (or REST API) can push packages to a repo, promote or copy packages between repos, and query repo/package status.


## Features

### Multi-architecture Debian repositories

By default, Debian repos use `binary-any/` (compatible with all packages).  Enable **multi-arch** mode per repo in Repo Settings to generate proper per-architecture directories:

- Uploaded packages are indexed under their actual architecture (e.g. `binary-amd64/`, `binary-arm64/`)
- Packages with `Architecture: all` appear in every arch index per Debian policy
- The generated setup instructions automatically reflect all detected architectures: `deb [arch=amd64,arm64 signed-by=...] ...`
- Existing repos default to `binary-any/` — opt in per-repo to avoid breaking existing clients

### Package retention policies

Configure automatic cleanup of old package versions per repository in Repo Settings:

| Policy | Behaviour |
|---|---|
| **Keep everything** | No automatic deletion (default) |
| **Keep latest N versions** | Keep the N most recent versions per package name + architecture |
| **Delete packages older than N days** | Remove packages uploaded more than N days ago |
| **Keep latest N versions AND delete older than N days** | Apply both rules — whichever removes more |

Retention is enforced:
1. Immediately after each upload or package copy
2. During the nightly background sweep (every 24 hours)

Packages that are referenced by another repository are never deleted regardless of policy.

> **Upgrading from an older version:** The `keep_only_latest` boolean flag has been replaced by retention policies. Existing repos that had `keep_only_latest=True` are automatically migrated to `retention_policy=keep_latest_n` with `retention_keep_count=1` — no manual action required.

### Package promotion

Each repository can be configured with a **Promote destination** repo.  Clicking "Promote" copies selected packages to that destination, making it easy to move packages through a pipeline (e.g. `dev → staging → production`).

The frontend highlights which packages in a repo are already present in the promotion target.

### PGP signing

Repositories can be assigned a PGP signing key.  On every rebuild:
- **Debian:** generates `Release.gpg` (detach-signed) and `InRelease` (clearsigned)
- **RPM:** signs `repodata/repomd.xml`
- The public key is exported to `public.gpg` inside the repo for client configuration

Signing keys are generated as 4096-bit RSA keys directly on the server.  Keys can also be imported from existing PEM files via the `import_pgp_private_key` management command.


## Users and Permissions

There are two levels of users:

  1. **Super User** — Full read/write access to all repositories plus admin access to add/remove users, keys, and permissions
  2. **Regular User** — Read access to all repositories.  Write access must be granted explicitly per repository

To add a new user:
  1. Log in as a super user and click **System Admin** in the top-right menu
  2. Click **Add** next to the Users link
  3. Set a username and password and click **Save** (an API token is created automatically)
  4. To grant write access, click **Repositories**, select a repo, add the user to the write access list, and save


## REST API

### Repo actions

    GET    /api/repos/                              # List all repos
    POST   /api/repos/                              # Create a repo
    GET    /api/<repo_uid>/                         # Repo details (includes setup instructions)
    PUT    /api/<repo_uid>/                         # Update repo settings (full update)
    PATCH  /api/<repo_uid>/                         # Partial update (e.g. signing key only)
    DELETE /api/<repo_uid>/                         # Delete a repo

### Package actions

    GET    /api/<repo_uid>/packages/                # List packages (searchable, sortable)
    POST   /api/<repo_uid>/upload/                  # Upload a package (async, returns task_id)
    GET    /api/upload-status/<task_id>/            # Poll upload task status
    GET    /api/<repo_uid>/pkg/<package_uid>/       # Package details
    DELETE /api/<repo_uid>/pkg/<package_uid>/       # Delete a package
    POST   /api/<repo_uid>/pkg/<package_uid>/copy/  # Copy package to another repo

### Signing key actions

    GET    /api/signingkeys/                        # List all signing keys
    POST   /api/signingkeys/                        # Generate a new signing key
    DELETE /api/signingkeys/<fingerprint>/          # Delete a signing key
    GET    /api/signingkeys/<fingerprint>/download/ # Download public key as .asc

### Build / log actions

    GET    /api/builds/                             # List repo builds (filterable)
    GET    /api/buildlogs/                          # List build log lines (filterable)

### Auth

    GET    /api/whoami                              # Current user info + API token

All endpoints require a token in the `Authorization` header:

    curl -H 'Authorization: Token <your-token>' http://localhost:7376/api/repos/


## Development

### Architecture

OpenRepo consists of four processes:

| Process | Role |
|---|---|
| **Nginx** | Serves static files, Vue frontend, and repo files; proxies `/api/` and `/admin/` to Django |
| **Django app server** | Hosts the REST API and admin interface |
| **Django worker** | Background process that regenerates repo metadata when packages change; runs nightly retention sweeps |
| **PostgreSQL** | Primary data store (SQLite supported for development) |

### Dev environment setup

Add `web/openrepo/settings_local.py`:

```python
import os

os.environ["OPENREPO_VAR_DIR"] = "/var/tmp/openrepo/"
os.environ["OPENREPO_DEBUG"] = "TRUE"
os.environ["OPENREPO_DB_TYPE"] = "sqlite"
os.environ["OPENREPO_LOGLEVEL"] = "DEBUG"
```

Run each process in a separate terminal:

```bash
# Tab 1 — Django dev server
cd web && ./manage.py runserver

# Tab 2 — background worker
cd web && ./manage.py runworker

# Tab 3 — Vue dev server (hot reload)
cd frontend && npm run dev

# Tab 4 — Nginx dev proxy
nginx -c /path/to/openrepo/deploy/nginx/nginx.conf.dev
```

Navigate to http://localhost:5173/ — both servers support live reload on code changes.

### Running tests

```bash
OPENREPO_VAR_DIR=/tmp/openrepo python3 web/manage.py test repo.tests
```

### Linting

```bash
# Python (from repo root)
flake8 .

# Frontend
cd frontend && npm run lint
```

### Management commands

| Command | Description |
|---|---|
| `./manage.py runworker` | Start the background worker (repo rebuilds + nightly retention sweep) |
| `./manage.py startup_checks` | Run at app startup — imports all DB keys into the local GPG keyring |
| `./manage.py refresh_keychain` | Re-import all PGP keys from the database into the local GPG keyring (useful after keyring is lost or moved) |
| `./manage.py import_pgp_private_key <path> [--passphrase <phrase>]` | Import an existing PGP private key from a PEM file into the database and keyring |
| `./manage.py migrate` | Apply database migrations |
| `./manage.py createsuperuser` | Create a new admin user |

### CI/CD workflows

Three GitHub Actions workflows run on every push:

| Workflow | File | Triggers |
|---|---|---|
| **CI** (Django + CLI tests) | `.github/workflows/main.yml` | push, pull_request, weekly schedule |
| **Lint** (flake8 + ESLint) | `.github/workflows/lint.yml` | push, pull_request |
| **Docker build & push** | `.github/workflows/docker-build.yml` | push to `main`, version tags, weekly schedule |

The Docker workflow pushes to `ghcr.io/opentreecz/openrepo:latest` and also tags by git SHA and semver.  The weekly scheduled runs rebuild against the latest base images so security patches land even without a code change.

### Code coverage

See [web/CODE_COVERAGE.md](web/CODE_COVERAGE.md) for full instructions on generating and interpreting coverage reports.

```bash
cd web
coverage run manage.py test repo.tests
coverage report
coverage html -d htmlcov/
```
