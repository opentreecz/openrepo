# openrepo_cli

The OpenRepo Command Line Interface (CLI) provides an easy way to integrate OpenRepo with CI/CD pipelines — upload packages when a build finishes, promote packages through environments, query repo state, and more.

## Installation

Download the standalone binary from the [Releases page](https://github.com/opentreecz/openrepo/releases):

```bash
sudo wget https://github.com/opentreecz/openrepo/releases/download/v1.0.0/openrepo_cli_$(uname -m) \
  -O /usr/local/bin/openrepo && sudo chmod +x /usr/local/bin/openrepo
```

Or run directly from source:

```bash
cd cli
pip install -r requirements.txt
PYTHONPATH=. python main.py --help
```

## Quick start

1. Log in to your OpenRepo server and go to **User Info** (`/cfg/userinfo/`)
2. Copy the CLI snippet — it sets your API key and server URL:

```bash
export OPENREPO_SERVER=http://repo.mydomain.com
export OPENREPO_APIKEY=abcdef1234567890abcdef1234567890abcdef12
openrepo list_repos
```

Output:

```
┌──────────────────┬───────────┬───────────────┬─────────────────────────────┐
│     repo_uid     │ repo_type │ package_count │         last_updated        │
├──────────────────┼───────────┼───────────────┼─────────────────────────────┤
│ acmewidgets-dev  │    deb    │       7       │ 2022-12-01T02:38:48.595892Z │
│ acmewidgets-prod │    deb    │       6       │ 2022-12-01T02:35:03.617695Z │
│     qatools      │   files   │       78      │ 2022-12-01T03:43:56.944487Z │
│   redhat-dist    │    rpm    │       5       │ 2022-12-01T03:44:10.676156Z │
└──────────────────┴───────────┴───────────────┴─────────────────────────────┘
```

## Global options

| Option | Env variable | Default | Description |
|---|---|---|---|
| `-k, --key` | `OPENREPO_APIKEY` | *(required)* | API token |
| `-s, --server` | `OPENREPO_SERVER` | `http://localhost:7376` | Server URL |
| `--debug` | — | off | Print full request/response detail |
| `--json` | — | off | Output as machine-readable JSON |

## Commands

### Repository commands

```bash
# List all repositories
openrepo list_repos

# Show full details for a repo (includes client setup instructions)
openrepo repo_details --repo_uid <repo_uid>

# Create a new repository
openrepo repo_create --repo_uid <repo_uid> --repo_type <deb|rpm|files> --signing_key <fingerprint>

# Delete a repository
openrepo repo_delete --repo_uid <repo_uid>
```

### Package commands

```bash
# List packages in a repository
openrepo list_packages --repo_uid <repo_uid>

# Show details for a single package
openrepo package_detail --repo_uid <repo_uid> --package_uid <package_uid>

# Upload one or more package files (async — waits for processing)
openrepo upload --repo_uid <repo_uid> /path/to/file.deb
openrepo upload --repo_uid <repo_uid> /path/to/*.rpm
openrepo upload --repo_uid <repo_uid> --overwrite /path/to/file.deb

# Copy a package to another repository
openrepo package_copy --src_repo_uid <src> --src_package_uid <uid> --dst_repo_uid <dst>

# Promote a package to the repo configured as "promote_to"
openrepo package_promote --src_repo_uid <repo_uid> --src_package_uid <package_uid>

# Delete a package
openrepo package_delete --repo_uid <repo_uid> --package_uid <package_uid>
```

### Signing key commands

```bash
# List all signing keys
openrepo list_signingkeys
```

## CI/CD examples

### Upload on every build (GitHub Actions)

```yaml
- name: Upload package to OpenRepo
  env:
    OPENREPO_SERVER: ${{ secrets.OPENREPO_SERVER }}
    OPENREPO_APIKEY: ${{ secrets.OPENREPO_APIKEY }}
  run: openrepo upload --repo_uid myapp-dev dist/myapp_1.0_amd64.deb
```

### Promote from dev to staging after tests pass

```bash
# Get the package uid of the version just uploaded
PKG_UID=$(openrepo list_packages --repo_uid myapp-dev --json | jq -r '.results[0].package_uid')

# Promote it
openrepo package_promote --src_repo_uid myapp-dev --src_package_uid "$PKG_UID"
```

### Overwrite a package (re-upload same version)

```bash
openrepo upload --repo_uid myapp-dev --overwrite dist/myapp_1.0_amd64.deb
```

## Architecture

The CLI communicates exclusively via the OpenRepo REST API, sending the API token in the `Authorization: Token <key>` header.  All commands map 1:1 to REST endpoints.

The CLI is written in Python and can be distributed as a standalone binary via `pyinstaller`.  Output is either human-readable tables (default) or JSON (`--json`).
