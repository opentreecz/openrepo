---
layout: default
title: Getting Started
nav_order: 2
---

<p align="center">
  <img src="https://raw.githubusercontent.com/opentreecz/.github/master/profile/img/opentreeczlogo.jpeg" alt="opentree.cz" width="120"/>
</p>

# Getting Started
{: .no_toc }

<details open markdown="block">
  <summary>Contents</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

## Prerequisites

- [Docker](https://docs.docker.com/engine/install/)
- [Docker Compose plugin](https://docs.docker.com/compose/install/)

## Installation

```bash
# Download the compose file and environment template
wget https://raw.githubusercontent.com/opentreecz/openrepo/main/docker-compose.yml
wget https://raw.githubusercontent.com/opentreecz/openrepo/main/.env.example

# Configure environment (OPENREPO_SECRET_KEY is required)
cp .env.example .env
# Generate a secret key and paste it into .env:
python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
$EDITOR .env

# Start all services
docker compose up -d

# Create the initial admin user
docker compose exec django ./django/manage.py createsuperuser
```

Navigate to **http://localhost:7376**

Default credentials:

| Field | Value |
|---|---|
| Username | `admin` |
| Password | `admin` |

{: .warning }
Change the default admin password immediately after first login.

---

## Environment variables

Copy `.env.example` to `.env` and configure before starting:

| Variable | Default | Description |
|---|---|---|
| `OPENREPO_SECRET_KEY` | *(required)* | Django secret key — **must be set**. Generate with: `python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'`. `DJANGO_SECRET_KEY` also accepted. |
| `OPENREPO_PG_PASSWORD` | `postgres` | PostgreSQL password |
| `OPENREPO_PG_HOSTNAME` | `localhost` | PostgreSQL host (`db` in Compose) |
| `OPENREPO_PG_PORT` | `5432` | PostgreSQL port |
| `OPENREPO_PG_CONN_MAX_AGE` | `300` | Connection lifetime in seconds; `0` disables persistence |
| `OPENREPO_PG_DATABASE` | `openrepo` | PostgreSQL database name |
| `OPENREPO_PG_USERNAME` | `postgres` | PostgreSQL username |
| `OPENREPO_PORT` | `7376` | Host port for the web UI |
| `OPENREPO_DB_TYPE` | `sqlite` | Database backend: `sqlite` or `postgresql` |
| `OPENREPO_VAR_DIR` | `/var/lib/openrepo/` | Base directory for all persistent data |
| `OPENREPO_DEBUG` | `FALSE` | Enable Django debug mode |
| `OPENREPO_LOGLEVEL` | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `OPENREPO_DOMAIN` | `localhost:8080` | Public domain name (used in repo setup instructions and `ALLOWED_HOSTS`) |
| `OPENREPO_ALLOWED_HOSTS` | *(none)* | Comma-separated additional hostnames for Django's `ALLOWED_HOSTS` (localhost, 127.0.0.1, and `OPENREPO_DOMAIN` are always included) |
| `OPENREPO_CSRF_TRUSTED_ORIGINS` | *(none)* | Space-separated trusted CSRF origins for reverse proxies |
| `OPENREPO_MAX_UPLOAD_SIZE` | `2147483648` | Maximum upload file size in bytes (default 2 GB) |
| `OPENREPO_REDIS_URL` | `redis://redis:6379/0` | Celery broker and result backend |
| `OPENREPO_CELERY_EAGER` | `0` | Set `1` for synchronous tasks in development/tests only |
| `OPENREPO_DISABLE_THROTTLE` | `0` | Set `1` to disable API throttling in development/tests |
| `OPENREPO_USE_PYTHON_TOOLS` | `0` | Set `1` to use pure-Python Debian/RPM repository tooling |
| `RPM_VERSION_IGNORE_BUILD_NUM` | `false` | Set `true` to strip the RPM release (build number) suffix from versions |

The complete commented template is [`.env.example`](https://github.com/opentreecz/openrepo/blob/main/.env.example).
For the Python CLI, export `OPENREPO_SERVER` (default `http://localhost:7376`)
and `OPENREPO_APIKEY` (your API token) in the shell running the command.

### Passing environment overrides into Docker

Compose reads `.env` for interpolation; it does not automatically pass all its
values into containers. The supplied Compose file interpolates
`OPENREPO_SECRET_KEY` (with `DJANGO_SECRET_KEY` as a fallback),
`OPENREPO_PG_DATABASE`, `OPENREPO_PG_USERNAME`, `OPENREPO_PG_PASSWORD`, and
`OPENREPO_PORT`. It fixes the database backend to PostgreSQL, host to `db`, port
to `5432`, and Redis URL to `redis://redis:6379/0`.

To make the Redis URL configurable, replace the existing Redis environment entry
in **each of Django, worker, and beat** with:

```yaml
      - OPENREPO_REDIS_URL=${OPENREPO_REDIS_URL:-redis://redis:6379/0}
```

Then set `OPENREPO_REDIS_URL` in `.env`. Add other application overrides to the
appropriate service's `environment` in the same way. Apply changes with
`docker compose up -d`; a plain restart does not reload container environment.
Native deployments must export variables or load them through their service
manager; Django does not automatically read this `.env` file.

### Uploads return HTTP 500 while package listing works

This indicates a failure in the server-side upload request. Listing packages
does not test storage writes or task dispatch. Uploads write the file, create an
`UploadTask`, and publish a Celery task before returning HTTP 202. An unavailable
Redis broker, storage errors, or database errors can interrupt these steps.
The generic HTML 500 response does not identify which step failed.

Inspect the Django traceback at the failed request's timestamp:

```bash
docker compose ps
docker compose logs --since 30m django worker redis
docker compose exec redis redis-cli ping
docker compose exec django ./django/manage.py migrate --check
docker compose exec django df -h /var/lib/openrepo /tmp
docker compose exec django df -i /var/lib/openrepo /tmp
```

The Redis command checks the bundled Redis service; for an external broker,
check that service and connectivity from Django instead. Confirm that Django
and workers use the same broker and shared storage. Correct the cause reported
by the traceback before retrying one project. Do not enable eager tasks as a
production workaround for a broken broker.

---

## Data persistence

All persistent data is stored in named Docker volumes:

| Volume | Contents |
|---|---|
| `openrepo-data` | Package files, GPG keyring, repo metadata, SQLite DB (if used) |
| `openrepo-pq` | PostgreSQL data files |

---

## Users and permissions

Two user levels:

1. **Super User** — full read/write access to all repos + admin panel
2. **Regular User** — read-only by default; write access granted per repo

To add a user:
1. Click **System Admin** in the top-right menu
2. Click **Add** next to Users
3. Set username and password — an API token is created automatically
4. To grant write access: click **Repositories**, select the repo, add the user to the write access list

---

## Upgrading

{: .note }
**From versions using `keep_only_latest`:** This flag has been replaced by [retention policies](features#package-retention-policies). Existing repos with `keep_only_latest=True` are automatically migrated to `retention_policy=keep_latest_n` with `retention_keep_count=1`. No manual action required.

---

## Other deployment methods

- [Bare-Metal Deployment](bare-metal) — install on Debian/Ubuntu, RHEL/Fedora, Arch Linux, Alpine Linux with systemd/OpenRC/SysVinit
- [OpenWrt Deployment](openwrt) — full server on OpenWrt with procd init and pure-Python tools
- [Multi-Architecture Guide](architecture-guide) — how to host packages for multiple CPU architectures in one repository

---

## Automated Sync with openrepo-sync

Once your repository is set up, you can use [openrepo-sync](https://github.com/opentreecz/openrepo-sync) to automatically mirror packages from upstream sources (GitHub Releases, Debian APT repos, RPM repos, SourceForge, direct URLs).

```sh
# Install and configure
docker pull ghcr.io/opentreecz/openrepo-sync:latest

# Create config pointing to your OpenRepo server
cat > config.yaml <<EOF
openrepo:
  api_url: "https://your-openrepo-server.com"
  api_key: "${OPENREPO_API_KEY}"
EOF

# Create a project file
cat > projects/nginx.yaml <<EOF
name: nginx
repo_uid: deb
keep_versions: 3
source:
  type: deb_repo
  url: https://nginx.org/packages/debian
  suites: bookworm
  package_filter: nginx
EOF

# Run sync
docker compose run --rm openrepo-sync --dry-run
docker compose run --rm openrepo-sync
```

Full documentation: [opentreecz.github.io/openrepo-sync](https://opentreecz.github.io/openrepo-sync/)
