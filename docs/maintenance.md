---
layout: default
title: Maintenance & Cleanup
nav_order: 7
---

<p align="center">
  <img src="assets/openrepo-logo.svg" alt="OpenRepo" width="360">
</p>

# Maintenance & Cleanup
{: .no_toc }

1. TOC
{:toc}

---

## Why cleanup is needed

Package files are deleted automatically when the **last** package row that
references them is deleted (retention policy, `DELETE /api/<repo>/pkg/<uid>/`,
openrepo-sync pruning). Some paths still leave data behind:

| Leftover | Cause |
|---|---|
| Stored file of an **abandoned upload** | The upload was saved (`stored`) but its processing job was lost (worker or broker restart), so the task never reached `completed`/`failed` |
| **Orphan package files** | Crashes between writing a file and creating its database row, or data from older releases |
| Builds stuck in **`running`** | The worker was killed during a build |
| **Stale publish directories** `<repo>.<N>` | Old directories are only removed after a *successful* build, so a run of failing builds leaves one directory per attempt |
| Upload-task and build **history** | Grows without bound (a build every few minutes adds up) |

## The cleanup procedure

`repo.cleanup.run_cleanup()` runs these steps in order:

1. **Abandoned uploads**: upload tasks still `uploading`, `stored` or `processing` after the grace period are marked `failed` ("Abandoned: upload was never processed").
2. **Stale builds**: builds still `running` after the grace period are marked `complete_fail` if a newer build of the same repo exists or no build of that repo holds the rebuild lock.
3. **Orphan files**: every file under `STORAGE_PATH` is removed unless it is
   - referenced by a package (`package_uid`),
   - the stored file of an upload task that is still in flight (younger than the grace period),
   - the target of a pool symlink anywhere in the publish tree, or
   - younger than the grace period (an upload writes its file *before* the task row exists).

   Empty storage sub-directories are removed afterwards.
4. **Stale publish directories**: `<repo>.<N>` directories in `REPO_WWW_PATH` that the `<repo>` symlink does not point to, older than the grace period. The repo's rebuild lock is held while deleting, and repos that are building right now are skipped. Directories of repos that **no longer exist in the database are only reported** (`unmanaged_publish_dirs`) and never deleted, because clients may still use them.
5. **History**: finished upload tasks and builds (with their log lines) older than `OPENREPO_CLEANUP_HISTORY_DAYS` are deleted. The latest build of every repo is always kept.

Only one cleanup runs at a time (`OPENREPO_VAR_DIR/locks/cleanup.lock`).
Every run logs a one-line summary, for example:

```
cleanup (apply): removed 424 orphan file(s) (59.90 GB), 3 stale publish dir(s), 243 empty dir(s); abandoned uploads=310, stale builds=1, old upload tasks=0, old builds=0, unmanaged publish dirs=1, errors=0
```

## Running it

### WebUI: Storage audit (report only)

Sign in as a superuser and choose **⋮ → Maintenance → Run storage audit**.
Run it off-peak: a Celery worker reads live APT, RPM, APK and generic indexes and
hashes package contents where the index supplies a checksum. The page shows counts,
candidate bytes and a paginated list. Filter by finding type or path. Check the
unreferenced files to include in a review list; the selection survives page and
filter changes until you leave or start another audit. **Export selected list**
downloads the selected paths, sizes and checksums. The full JSON Lines manifest
is also available. Neither export performs cleanup.

**Filename needs review** flags literal percent escapes, invisible characters,
invalid bytes, and leading/trailing whitespace. Similar spellings next to a
missing indexed path are hints, not identity matches. A normal `~`, `-`, `_`
or internal space alone does not flag a healthy file. Filename warnings cannot
be checked for removal.
Both the web and worker processes must use the same `OPENREPO_VAR_DIR` and data mounts.
Reports older than one day are pruned on the next audit.

An indexed path missing locally, a checksum mismatch, or a database package not
reachable through the index is a publication issue. Keep the payload. Candidates
exclude database references, all in-flight uploads, published symlink targets,
multiply-linked files, files less than seven days old, and checksum matches for
broken index entries. Incomplete coverage prevents candidate classification.
The audit checks local paths, not the HTTP proxy, cached client indexes or direct
downloads. A candidate is for investigation, not a deletion authorization.
The page cannot apply cleanup and does not change periodic cleanup settings.

### Automatically

The Celery beat schedule runs `repo.tasks.cleanup_task` every
`OPENREPO_CLEANUP_INTERVAL` seconds (default: daily). Set
`OPENREPO_CLEANUP_DRY_RUN=1` to only log what it would remove, or
`OPENREPO_CLEANUP_INTERVAL=0` to disable the periodic run.

### Manually (`manage.py cleanup`)

Dry-run by default:

```bash
docker compose exec worker python manage.py cleanup            # report only
docker compose exec worker python manage.py cleanup --apply    # delete
docker compose exec worker python manage.py cleanup --apply --grace-hours 6 --history-days 30
docker compose exec worker python manage.py cleanup --json     # machine-readable report
```

### Over the API

`POST /api/cleanup/` (superuser API key). Dry-run unless `"dry_run": false`:

```bash
curl -X POST http://localhost:7376/api/cleanup/ \
  -H 'Authorization: Token <superuser-token>' \
  -H 'Content-Type: application/json' \
  -d '{"dry_run": false}'
```

Returns the report (`orphan_files`, `orphan_bytes`, `abandoned_uploads`,
`stale_builds`, `stale_publish_dirs`, `unmanaged_publish_dirs`,
`old_upload_tasks`, `old_builds`, `skipped`, `errors`). It answers
`409 CLEANUP_BUSY` while another cleanup runs. openrepo-sync can call this
endpoint after every sync pass (`cleanup.server` in its `config.yaml`).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `OPENREPO_CLEANUP_INTERVAL` | `86400` | Seconds between automatic runs; `0` disables them |
| `OPENREPO_CLEANUP_DRY_RUN` | `0` | `1` = automatic runs only log what they would remove |
| `OPENREPO_CLEANUP_GRACE_HOURS` | `24` | Minimum age before files, uploads, builds and publish directories count as abandoned |
| `OPENREPO_CLEANUP_HISTORY_DAYS` | `90` | Finished upload tasks/builds older than this are deleted; `0` keeps all history |
| `OPENREPO_SUBPROCESS_TIMEOUT` | `3600` | Build tool timeout. Too low a value makes builds fail repeatedly, which is what leaves stale publish directories behind |

## Things cleanup does not touch

- Packages themselves: removing old versions is the job of the per-repo
  [retention policy](features.md#package-retention-policies) or of
  openrepo-sync's `keep_versions`.
- Publish directories of deleted repos: remove them by hand once no client
  uses them.
- The `apt-ftparchive` cache (`debcache.db`) and the RPM cache.
