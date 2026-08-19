---
layout: default
title: Bare-Metal Deployment
nav_order: 7
---

# Bare-Metal Deployment
{: .no_toc }

<details open markdown="block">
  <summary>Contents</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

## Overview

While Docker is the recommended deployment method, OpenRepo can be installed directly on a Linux server. This guide covers installation on Debian/Ubuntu, RHEL/Fedora, and Arch Linux systems with support for systemd, OpenRC, and SysVinit init systems.

---

## Prerequisites

| Component | Purpose |
|---|---|
| Python 3.10+ | Django backend runtime |
| PostgreSQL 14+ | Database |
| Nginx | Reverse proxy and static file serving |
| createrepo-c | RPM repository metadata generation |
| GnuPG | PGP key management and package signing |
| libapt-pkg-dev | Debian package metadata extraction |
| Node.js 20+ | Frontend build (build-time only) |

---

## Installation from packages

### Debian/Ubuntu (.deb)

```bash
# Download from GitHub Releases
wget https://github.com/opentreecz/openrepo/releases/latest/download/openrepo_latest_all.deb

# Install
sudo apt install ./openrepo_latest_all.deb

# Configure
sudo nano /etc/openrepo/openrepo.env

# Start services
sudo systemctl enable --now openrepo-web openrepo-worker
```

### RHEL/Fedora (.rpm)

```bash
# Download from GitHub Releases
wget https://github.com/opentreecz/openrepo/releases/latest/download/openrepo-latest.noarch.rpm

# Install
sudo dnf install ./openrepo-latest.noarch.rpm

# Configure
sudo nano /etc/openrepo/openrepo.env

# Start services
sudo systemctl enable --now openrepo-web openrepo-worker
```

### Arch Linux

```bash
cd /tmp
git clone https://github.com/opentreecz/openrepo.git
cd openrepo/packaging/archlinux
makepkg -si

# Configure
sudo nano /etc/openrepo/openrepo.env

# Start services
sudo systemctl enable --now openrepo-web openrepo-worker
```

---

## Manual installation

### 1. Install system dependencies

**Debian/Ubuntu:**
```bash
sudo apt-get install -y \
    python3 python3-venv python3-pip \
    postgresql nginx createrepo-c gnupg \
    libapt-pkg-dev libpq-dev python3-dev \
    build-essential
```

**RHEL/Fedora:**
```bash
sudo dnf install -y \
    python3 python3-pip python3-devel \
    postgresql-server postgresql-devel nginx \
    createrepo_c gnupg2
```

### 2. Create system user

```bash
sudo useradd --system --home-dir /opt/openrepo --shell /usr/sbin/nologin openrepo
```

### 3. Set up application directory

```bash
sudo mkdir -p /opt/openrepo /var/lib/openrepo/{storage,repos,keyring}
sudo chown -R openrepo:openrepo /opt/openrepo /var/lib/openrepo

# Clone or extract the application
sudo -u openrepo git clone https://github.com/opentreecz/openrepo.git /opt/openrepo/src
sudo -u openrepo cp -r /opt/openrepo/src/web/* /opt/openrepo/
```

### 4. Set up Python virtual environment

```bash
sudo -u openrepo python3 -m venv /opt/openrepo/venv
sudo -u openrepo /opt/openrepo/venv/bin/pip install -r /opt/openrepo/requirements.txt
```

### 5. Build frontend

```bash
cd /opt/openrepo/src/frontend
npm ci
npm run build
sudo -u openrepo cp -r dist /opt/openrepo/frontend-dist
```

### 6. Configure PostgreSQL

```bash
sudo -u postgres createuser openrepo
sudo -u postgres createdb -O openrepo openrepo
sudo -u postgres psql -c "ALTER USER openrepo PASSWORD 'your-secure-password';"
```

### 7. Configure OpenRepo

```bash
sudo mkdir -p /etc/openrepo
sudo cp /opt/openrepo/src/.env.example /etc/openrepo/openrepo.env
sudo chmod 640 /etc/openrepo/openrepo.env
sudo chown root:openrepo /etc/openrepo/openrepo.env
```

Edit `/etc/openrepo/openrepo.env`:
```bash
OPENREPO_SECRET_KEY=your-random-secret-key-here
OPENREPO_DB_TYPE=postgresql
OPENREPO_PG_HOSTNAME=localhost
OPENREPO_PG_DATABASE=openrepo
OPENREPO_PG_USERNAME=openrepo
OPENREPO_PG_PASSWORD=your-secure-password
OPENREPO_VAR_DIR=/var/lib/openrepo/
OPENREPO_DOMAIN=your-server.example.com
OPENREPO_LOGLEVEL=INFO
```

### 8. Run migrations and create admin

```bash
cd /opt/openrepo
sudo -u openrepo bash -c '
    source /opt/openrepo/venv/bin/activate
    export $(cat /etc/openrepo/openrepo.env | grep -v "^#" | xargs)
    python manage.py migrate
    python manage.py createsuperuser
'
```

### 9. Configure Nginx

```nginx
# /etc/nginx/sites-available/openrepo
server {
    listen 8080;
    server_name _;
    client_max_body_size 5000M;

    # Frontend
    location / {
        root /opt/openrepo/frontend-dist;
        try_files $uri $uri/ /index.html;
    }

    # Django API and Admin
    location ~ ^/(api|admin)/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Repository files
    location /repos/ {
        alias /var/lib/openrepo/repos/;
        autoindex on;
    }

    # Health check
    location /health/ {
        return 200 "OK";
    }
}
```

Enable the site:
```bash
sudo ln -s /etc/nginx/sites-available/openrepo /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## Init system configuration

### systemd (recommended)

Copy the provided service files:
```bash
sudo cp packaging/systemd/openrepo-web.service /etc/systemd/system/
sudo cp packaging/systemd/openrepo-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now openrepo-web openrepo-worker
```

Check status:
```bash
sudo systemctl status openrepo-web openrepo-worker
sudo journalctl -u openrepo-web -f
```

### OpenRC (Alpine, Gentoo, Artix)

Copy the provided init scripts:
```bash
sudo cp packaging/openrc/openrepo-web /etc/init.d/
sudo cp packaging/openrc/openrepo-worker /etc/init.d/
sudo chmod +x /etc/init.d/openrepo-web /etc/init.d/openrepo-worker
sudo rc-update add openrepo-web default
sudo rc-update add openrepo-worker default
sudo rc-service openrepo-web start
sudo rc-service openrepo-worker start
```

### SysVinit (legacy systems)

Copy the provided init scripts:
```bash
sudo cp packaging/sysvinit/openrepo-web /etc/init.d/
sudo cp packaging/sysvinit/openrepo-worker /etc/init.d/
sudo chmod +x /etc/init.d/openrepo-web /etc/init.d/openrepo-worker
sudo update-rc.d openrepo-web defaults
sudo update-rc.d openrepo-worker defaults
sudo service openrepo-web start
sudo service openrepo-worker start
```

---

## Directory layout

| Path | Purpose |
|---|---|
| `/opt/openrepo/` | Application code and Python virtualenv |
| `/etc/openrepo/openrepo.env` | Configuration file |
| `/var/lib/openrepo/storage/` | Uploaded package file storage |
| `/var/lib/openrepo/repos/` | Generated repository metadata |
| `/var/lib/openrepo/keyring/` | GPG keyring for PGP signing |

---

## Upgrading

```bash
# Stop services
sudo systemctl stop openrepo-web openrepo-worker

# Update application
cd /opt/openrepo/src
sudo -u openrepo git pull

# Update Python dependencies
sudo -u openrepo /opt/openrepo/venv/bin/pip install -r web/requirements.txt

# Rebuild frontend
cd frontend && npm ci && npm run build
sudo -u openrepo cp -r dist /opt/openrepo/frontend-dist

# Run migrations
cd /opt/openrepo
sudo -u openrepo bash -c '
    source venv/bin/activate
    export $(cat /etc/openrepo/openrepo.env | grep -v "^#" | xargs)
    python manage.py migrate
'

# Restart services
sudo systemctl start openrepo-web openrepo-worker
```

---

## Security considerations

- Run OpenRepo behind a reverse proxy (Nginx) with TLS
- Set a strong `OPENREPO_SECRET_KEY` in production
- Restrict file permissions on `/etc/openrepo/openrepo.env` (contains passwords)
- Use firewall rules to restrict access to PostgreSQL (port 5432)
- The systemd service files include security hardening directives (`NoNewPrivileges`, `ProtectSystem`, etc.)
- Change the default admin password immediately after installation
