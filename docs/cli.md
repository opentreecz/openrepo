---
layout: default
title: CLI
nav_order: 5
---

<p align="center">
  <img src="https://raw.githubusercontent.com/opentreecz/.github/master/profile/img/opentreeczlogo.jpeg" alt="opentree.cz" width="120"/>
</p>

# CLI — openrepo_cli
{: .no_toc }

<details open markdown="block">
  <summary>Contents</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

## Installation

**Binary (recommended):**
```bash
sudo wget https://github.com/opentreecz/openrepo/releases/download/v1.0.0/openrepo_cli_$(uname -m) \
  -O /usr/local/bin/openrepo && sudo chmod +x /usr/local/bin/openrepo
```

**From source:**
```bash
cd cli
pip install -r requirements.txt
PYTHONPATH=. python main.py --help
```

---

## Configuration

Set the server URL and API key via environment variables (or pass as flags on every command):

```bash
export OPENREPO_SERVER=http://repo.mydomain.com
export OPENREPO_APIKEY=abcdef1234567890abcdef1234567890abcdef12
openrepo list_repos
```

Find your API key at **User Info** → `/cfg/userinfo/` on the server.

---

## Global options

| Option | Env variable | Default | Description |
|---|---|---|---|
| `-k, --key` | `OPENREPO_APIKEY` | *(required)* | API token |
| `-s, --server` | `OPENREPO_SERVER` | `http://localhost:7376` | Server URL |
| `--debug` | — | off | Print full request/response detail |
| `--json` | — | off | Output as machine-readable JSON |

---

## Commands

### Repository commands

```bash
openrepo list_repos
openrepo repo_details     --repo_uid <uid>
openrepo repo_create      --repo_uid <uid> --repo_type <deb|rpm|files> --signing_key <fingerprint>
openrepo repo_delete      --repo_uid <uid>
```

### Package commands

```bash
openrepo list_packages    --repo_uid <uid>
openrepo package_detail   --repo_uid <uid> --package_uid <uid>
openrepo upload           --repo_uid <uid> [--overwrite] <file> [<file> ...]
openrepo package_copy     --src_repo_uid <uid> --src_package_uid <uid> --dst_repo_uid <uid>
openrepo package_promote  --src_repo_uid <uid> --src_package_uid <uid>
openrepo package_delete   --repo_uid <uid> --package_uid <uid>
```

### Signing key commands

```bash
openrepo list_signingkeys
```

---

## CI/CD examples

### Upload on every build (GitHub Actions)

```yaml
- name: Upload to OpenRepo
  env:
    OPENREPO_SERVER: ${{ secrets.OPENREPO_SERVER }}
    OPENREPO_APIKEY: ${{ secrets.OPENREPO_APIKEY }}
  run: openrepo upload --repo_uid myapp-dev dist/myapp_1.0_amd64.deb
```

### Promote from dev to staging after tests pass

```bash
PKG_UID=$(openrepo list_packages --repo_uid myapp-dev --json | jq -r '.results[0].package_uid')
openrepo package_promote --src_repo_uid myapp-dev --src_package_uid "$PKG_UID"
```

### Overwrite a package (re-upload same version)

```bash
openrepo upload --repo_uid myapp-dev --overwrite dist/myapp_1.0_amd64.deb
```

### Get repo setup instructions

```bash
openrepo repo_details --repo_uid myapp-prod
# Prints the apt/yum config snippet to add on client machines
```
