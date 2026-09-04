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
wget https://raw.githubusercontent.com/opentreecz/openrepo/main/docker-compose.yml
docker compose up -d
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
| `OPENREPO_PG_HOSTNAME` | `db` | PostgreSQL host |
| `OPENREPO_PG_DATABASE` | `openrepo` | PostgreSQL database name |
| `OPENREPO_PG_USERNAME` | `postgres` | PostgreSQL username |
| `OPENREPO_DB_TYPE` | `sqlite` | Database backend: `sqlite` or `postgresql` |
| `OPENREPO_VAR_DIR` | `/var/lib/openrepo/` | Base directory for all persistent data |
| `OPENREPO_DEBUG` | `FALSE` | Enable Django debug mode |
| `OPENREPO_LOGLEVEL` | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `OPENREPO_DOMAIN` | `localhost:8080` | Public domain name (used in repo setup instructions and `ALLOWED_HOSTS`) |
| `OPENREPO_ALLOWED_HOSTS` | *(none)* | Comma-separated additional hostnames for Django's `ALLOWED_HOSTS` (localhost, 127.0.0.1, and `OPENREPO_DOMAIN` are always included) |
| `OPENREPO_CSRF_TRUSTED_ORIGINS` | *(none)* | Space-separated trusted CSRF origins for reverse proxies |
| `OPENREPO_MAX_UPLOAD_SIZE` | `2147483648` | Maximum upload file size in bytes (default 2 GB) |
| `RPM_VERSION_IGNORE_BUILD_NUM` | `false` | Set `true` to strip the RPM release (build number) suffix from versions |

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
