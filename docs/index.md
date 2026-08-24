---
layout: home
title: Home
nav_order: 1
---

<p align="center">
  <img src="https://raw.githubusercontent.com/opentreecz/.github/master/profile/img/opentreeczlogo.jpeg" alt="opentree.cz" width="150"/>
</p>

# OpenRepo

**OpenRepo** is a self-hosted web server for managing and hosting Debian APT, Red Hat RPM, and generic package repositories.

The current release line emphasizes reliable repository rebuilds, validated uploads, multi-architecture package handling, and continuously published GitHub Pages documentation.

[![CI](https://github.com/opentreecz/openrepo/actions/workflows/main.yml/badge.svg)](https://github.com/opentreecz/openrepo/actions/workflows/main.yml)
[![Lint](https://github.com/opentreecz/openrepo/actions/workflows/lint.yml/badge.svg)](https://github.com/opentreecz/openrepo/actions/workflows/lint.yml)
[![Docker](https://github.com/opentreecz/openrepo/actions/workflows/docker-build.yml/badge.svg)](https://github.com/opentreecz/openrepo/actions/workflows/docker-build.yml)

---

## What is OpenRepo?

OpenRepo lets you host your own package repositories for Linux systems — without relying on external services. Upload packages through the web UI, CLI, or REST API, and your clients install them with standard tools like `apt` and `dnf`.

**Key features:**

| Feature | Description |
|---|---|
| **Deb / RPM / Generic** | Host all three repo types from one server |
| **Multi-arch Debian** | Per-architecture `binary-amd64/`, `binary-arm64/` dirs with proper `arch=all` handling |
| **Package retention** | Auto-prune old versions by count, age, or both |
| **PGP signing** | Repo-level signing with 4096-bit RSA keys, generated or imported |
| **Promotion chains** | One-click promotion across dev → staging → production |
| **REST API + CLI** | Full API coverage; CLI for CI/CD integration |
| **Async uploads** | Drag-and-drop upload with real-time status tracking |
| **Access control** | Per-repo write access for regular users |

---

## Quick start

```bash
wget https://raw.githubusercontent.com/opentreecz/openrepo/main/docker-compose.yml
docker compose up -d
```

Navigate to **http://localhost:7376**

Default credentials: `admin` / `admin` — **change immediately after first login.**

---

## Documentation

- [Getting Started](getting-started) — installation, environment variables, first steps
- [Features](features) — multi-arch repos, retention policies, promotion, signing
- [REST API](api) — full endpoint reference
- [CLI](cli) — command-line interface for CI/CD
- [Multi-Architecture Guide](architecture-guide) — supported architectures, multi-arch setup
- [Development](development) — architecture, dev setup, tests, management commands
- [Bare-Metal Deployment](bare-metal) — systemd, OpenRC, SysVinit, Alpine Linux
- [OpenWrt Deployment](openwrt) — full server on OpenWrt with procd

---

## Local Quality Checks

```bash
cd web
OPENREPO_VAR_DIR=/tmp/openrepo/ coverage run manage.py test repo.tests --verbosity=2
coverage report --show-missing --fail-under=85
flake8 --config=.flake8 .

cd ../cli
PYTHONPATH=. python tests/test_cli.py
flake8 --config=.flake8 .

cd ../frontend
npm ci
npm run type-check
npm run lint
npm run build
```

---

## Source & License

> **GitHub Repository:** [github.com/opentreecz/openrepo](https://github.com/opentreecz/openrepo) — source code, issues, pull requests, releases

Source code: [github.com/opentreecz/openrepo](https://github.com/opentreecz/openrepo)

OpenRepo is a fork of [openkilt/openrepo](https://github.com/openkilt/openrepo), extended with multi-arch support, retention policies, improved CI, and comprehensive test coverage.

Licensed under the [GNU Affero General Public License v3.0](https://github.com/opentreecz/openrepo/blob/main/LICENSE).
