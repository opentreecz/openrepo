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
| `OPENREPO_SECRET_KEY` | *(insecure built-in)* | Django secret key — **always set in production**. `DJANGO_SECRET_KEY` also accepted. |
| `OPENREPO_PG_PASSWORD` | `postgres` | PostgreSQL password |
| `OPENREPO_PG_HOSTNAME` | `db` | PostgreSQL host |
| `OPENREPO_PG_DATABASE` | `openrepo` | PostgreSQL database name |
| `OPENREPO_PG_USERNAME` | `postgres` | PostgreSQL username |
| `OPENREPO_DB_TYPE` | `sqlite` | Database backend: `sqlite` or `postgresql` |
| `OPENREPO_VAR_DIR` | `/var/lib/openrepo/` | Base directory for all persistent data |
| `OPENREPO_DEBUG` | `FALSE` | Enable Django debug mode |
| `OPENREPO_LOGLEVEL` | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `OPENREPO_DOMAIN` | `localhost:8080` | Public domain name (used in repo setup instructions) |
| `OPENREPO_SECURE_HOSTS` | `FALSE` | Set `TRUE` to restrict `ALLOWED_HOSTS` to localhost and `OPENREPO_DOMAIN` |
| `OPENREPO_CSRF_TRUSTED_ORIGINS` | *(none)* | Space-separated trusted CSRF origins for reverse proxies |
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
