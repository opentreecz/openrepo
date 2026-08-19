---
layout: default
title: OpenWrt Deployment
nav_order: 9
---

<p align="center">
  <img src="https://raw.githubusercontent.com/opentreecz/.github/master/profile/img/opentreeczlogo.jpeg" alt="opentree.cz" width="120"/>
</p>

# OpenWrt Deployment
{: .no_toc }

> **GitHub Repository:** [github.com/opentreecz/openrepo](https://github.com/opentreecz/openrepo)

<details open markdown="block">
  <summary>Contents</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

## Overview

OpenRepo can run as a full package repository server on OpenWrt devices. This is suitable for:

- **x86_64 OpenWrt VMs** — running OpenWrt as a router/firewall VM with extra services
- **High-end ARM boards** — Raspberry Pi 4, NanoPi R4S/R5S, Banana Pi, etc.
- **Purpose-built appliances** — custom hardware with 256MB+ RAM

{: .warning }
**Minimum requirements:** 256MB RAM, 128MB flash/storage. Most consumer routers (64-128MB RAM) do NOT meet these requirements.

---

## How it works on OpenWrt

Since OpenWrt doesn't have `apt-ftparchive` or `createrepo_c` available (they have complex C library dependencies that are impractical to cross-compile for all OpenWrt targets), OpenRepo uses **pure-Python fallback tools** for repository metadata generation.

This is controlled by the environment variable `OPENREPO_USE_PYTHON_TOOLS=1`, which is set automatically by the procd init script. **This only affects OpenWrt** — all other deployment methods (Docker, DEB, RPM, Arch, bare-metal) continue using native C tools.

| Feature | Standard (Docker/DEB/RPM) | OpenWrt |
|---|---|---|
| Debian `Packages`/`Packages.gz` | `apt-ftparchive` | Pure-Python generator |
| RPM `repomd.xml` | `createrepo_c` | Pure-Python generator (uses `rpmfile`) |
| Database | PostgreSQL | SQLite |
| Init system | systemd/OpenRC/SysVinit | procd |
| Configuration | `/etc/openrepo/openrepo.env` | UCI (`/etc/config/openrepo`) |

---

## Supported OpenWrt target architectures

The `openrepo-cli` package is architecture-independent (`PKGARCH:=all`) and works on any OpenWrt target.

The `openrepo-server` package is also architecture-independent (pure Python) but requires sufficient resources:

| Architecture | Example Devices | Suitable for Server? |
|---|---|---|
| `x86_64` | VMs, PC Engines APU | Yes |
| `aarch64_cortex-a53` | Raspberry Pi 3/4, NanoPi R2S | Yes (RPi 4 with 2GB+) |
| `aarch64_cortex-a72` | NanoPi R4S/R5S, RockPro64 | Yes |
| `aarch64_generic` | Generic AArch64 boards | Depends on RAM |
| `arm_cortex-a7_neon-vfpv4` | Banana Pi, Orange Pi | Marginal (check RAM) |
| `arm_cortex-a9_vfpv3-d16` | Marvell-based NAS | Possibly |
| `mipsel_24kc` | MT7621 routers | No (typically 128MB RAM) |
| `mips_24kc` | QCA routers | No (typically 64-128MB RAM) |

---

## Installation

### From opkg feed

```bash
# Update package lists
opkg update

# Install the full server
opkg install openrepo-server

# Or install just the CLI client
opkg install openrepo-cli
```

### Manual installation

If the package isn't in your feed:

```bash
# Install dependencies
opkg update
opkg install python3 python3-pip python3-setuptools python3-openssl \
    python3-sqlite3 nginx-ssl gnupg sqlite3-cli

# Create application directory
mkdir -p /opt/openrepo/data/{storage,repos,keyring}

# Clone and install
cd /opt/openrepo
wget https://github.com/opentreecz/openrepo/archive/v2.2.0.tar.gz
tar xzf v2.2.0.tar.gz --strip-components=1

# Create virtual environment
python3 -m venv /opt/openrepo/venv
/opt/openrepo/venv/bin/pip install django djangorestframework \
    django-filter gunicorn gevent rpmfile

# Run migrations
export OPENREPO_USE_PYTHON_TOOLS=1
export OPENREPO_VAR_DIR=/opt/openrepo/data/
export OPENREPO_DB_TYPE=sqlite
cd /opt/openrepo/web
/opt/openrepo/venv/bin/python manage.py migrate --noinput
/opt/openrepo/venv/bin/python manage.py createsuperuser
```

---

## Configuration

### UCI configuration

Edit `/etc/config/openrepo`:

```
config openrepo 'main'
    option enabled '1'
    option port '8000'
    option workers '2'
    option db_type 'sqlite'
    option var_dir '/opt/openrepo/data'
    option use_python_tools '1'
    option loglevel 'INFO'
```

| Option | Default | Description |
|---|---|---|
| `enabled` | `1` | Enable/disable the service |
| `port` | `8000` | HTTP port for the Django/Gunicorn server |
| `workers` | `2` | Number of Gunicorn worker processes |
| `db_type` | `sqlite` | Database backend (`sqlite` recommended for OpenWrt) |
| `var_dir` | `/opt/openrepo/data` | Base directory for storage, repos, and keyring |
| `use_python_tools` | `1` | Use pure-Python metadata generators (required on OpenWrt) |
| `loglevel` | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

### Nginx reverse proxy

The package installs an Nginx config at `/etc/nginx/conf.d/openrepo.conf`. Ensure Nginx is configured to include this:

```bash
# Edit /etc/nginx/nginx.conf to include conf.d/*.conf
/etc/init.d/nginx restart
```

---

## Service management

OpenRepo uses **procd** (OpenWrt's process supervisor):

```bash
# Enable at boot
/etc/init.d/openrepo enable

# Start the service (starts both web server and worker)
/etc/init.d/openrepo start

# Stop
/etc/init.d/openrepo stop

# Restart
/etc/init.d/openrepo restart

# Check status
ps | grep -E "(gunicorn|runworker)"
```

The procd init script manages two instances:
- **web** — Gunicorn serving the Django REST API
- **worker** — Background process for repo regeneration and retention sweeps

Both are automatically respawned if they crash.

---

## Limitations

| Limitation | Impact | Workaround |
|---|---|---|
| No `apt-ftparchive` | Deb repos use Python fallback | Functionally equivalent; slightly slower for 1000+ packages |
| No `createrepo_c` | RPM repos use Python fallback | Functionally equivalent; uses `rpmfile` for header reading |
| SQLite only | Single-writer concurrency | Sufficient for typical use (< 100 concurrent requests) |
| No Node.js | Cannot build frontend on device | Frontend must be pre-built and deployed as static files |
| Limited RAM | May OOM with very large repos | Keep repos under 500 packages; use swap if available |
| No PGP key generation | `gpg --gen-key` may be slow | Import pre-generated keys via management command |

---

## Performance considerations

- **2 Gunicorn workers** is recommended for 256MB RAM devices
- **SQLite** handles concurrent reads well but serializes writes
- The pure-Python `Packages` generator processes ~50 packages/second
- The pure-Python RPM metadata generator processes ~30 packages/second
- For repos with 100+ packages, expect repo regeneration to take 5-10 seconds

---

## Troubleshooting

### Not enough memory

```bash
# Check available memory
free -m

# Add swap (if storage allows)
dd if=/dev/zero of=/opt/swap bs=1M count=256
mkswap /opt/swap
swapon /opt/swap
```

### Service won't start

```bash
# Check logs
logread | grep openrepo

# Test manually
cd /opt/openrepo/web
export OPENREPO_USE_PYTHON_TOOLS=1 OPENREPO_VAR_DIR=/opt/openrepo/data/ OPENREPO_DB_TYPE=sqlite
/opt/openrepo/venv/bin/python manage.py runserver 0.0.0.0:8000
```

### Storage full

```bash
# Check disk usage
df -h

# Clean old repo builds
rm -rf /opt/openrepo/data/repos/*.old
```
