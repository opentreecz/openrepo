---
layout: default
title: REST API
nav_order: 4
---

# REST API
{: .no_toc }

<details open markdown="block">
  <summary>Contents</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

## Authentication

All endpoints require a token in the `Authorization` header:

```bash
curl -H 'Authorization: Token <your-token>' http://localhost:7376/api/repos/
```

Tokens are auto-generated when users are created. Find yours at `/cfg/userinfo/` or via `/api/whoami`.

---

## Repo endpoints

```
GET    /api/repos/                              List all repos
POST   /api/repos/                              Create a repo
GET    /api/<repo_uid>/                         Repo details + setup instructions
PUT    /api/<repo_uid>/                         Full update of repo settings
PATCH  /api/<repo_uid>/                         Partial update (e.g. signing key only)
DELETE /api/<repo_uid>/                         Delete a repo
```

**Create repo example:**
```bash
curl -X POST http://localhost:7376/api/repos/ \
  -H 'Authorization: Token <token>' \
  -F "repo_uid=myapp-dev" \
  -F "repo_type=deb" \
  -F "signing_key=<FINGERPRINT>"
```

**Repo fields (PUT/PATCH):**

| Field | Type | Description |
|---|---|---|
| `repo_uid` | string | Unique identifier (slug) |
| `repo_type` | `deb` \| `rpm` \| `files` | Repository type |
| `signing_key` | fingerprint string | PGP key fingerprint (nullable) |
| `promote_to` | repo_uid string | Destination repo for promotion (nullable) |
| `retention_policy` | string | `none`, `keep_latest_n`, `max_age_days`, `keep_latest_n_and_age` |
| `retention_keep_count` | integer | Versions to keep (used by count-based policies) |
| `retention_max_age_days` | integer | Max age in days (used by age-based policies) |
| `multi_arch` | boolean | Enable per-architecture dirs (deb repos only) |

---

## Package endpoints

```
GET    /api/<repo_uid>/packages/                List packages (search + sort supported)
POST   /api/<repo_uid>/upload/                  Upload a package (async, returns task_id)
GET    /api/upload-status/<task_id>/            Poll upload task status
GET    /api/<repo_uid>/pkg/<package_uid>/       Package details
DELETE /api/<repo_uid>/pkg/<package_uid>/       Delete a package
POST   /api/<repo_uid>/pkg/<package_uid>/copy/  Copy package to another repo
```

**Upload example:**
```bash
curl -X POST http://localhost:7376/api/myapp-dev/upload/ \
  -H 'Authorization: Token <token>' \
  -F "package_file=@myapp_1.0_amd64.deb"
# Returns: {"task_id": "<uuid>"}
```

**Poll upload status:**
```bash
curl http://localhost:7376/api/upload-status/<task_id>/ \
  -H 'Authorization: Token <token>'
# Returns: {"status": "completed", "result_data": {...}}
```

**Upload status values:** `uploading` → `processing` → `completed` / `failed`

**List packages query parameters:**

| Parameter | Description |
|---|---|
| `search` | Filter by package_name, filename, version, architecture |
| `ordering` | Sort field: `package_name`, `version`, `architecture`, `upload_date` (prefix `-` for descending) |
| `page_size` | Results per page (default 2000) |

---

## Signing key endpoints

```
GET    /api/signingkeys/                        List all signing keys
POST   /api/signingkeys/                        Generate a new signing key
DELETE /api/signingkeys/<fingerprint>/          Delete a signing key
GET    /api/signingkeys/<fingerprint>/download/ Download public key as .asc
```

**Generate key example:**
```bash
curl -X POST http://localhost:7376/api/signingkeys/ \
  -H 'Authorization: Token <token>' \
  -F "name=My Org" \
  -F "email=packages@myorg.com"
```

---

## Build and log endpoints

```
GET    /api/builds/       List repo builds
GET    /api/buildlogs/    List build log lines
```

**Filter builds by repo:**
```bash
curl 'http://localhost:7376/api/builds/?repo__repo_uid=myapp-dev' \
  -H 'Authorization: Token <token>'
```

**Build completion_status values:** `running`, `complete_success`, `complete_fail`

---

## Auth endpoint

```
GET    /api/whoami        Current user info and API token
```
