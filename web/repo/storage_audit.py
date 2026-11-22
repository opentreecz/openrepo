# SPDX-License-Identifier: AGPL-3.0-only
"""Read-only reconciliation of OpenRepo's live indexes, publish links and storage."""
import base64
import gzip
import hashlib
import json
import os
import re
import stat
import tarfile
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import TextIOWrapper
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

from django.conf import settings

from repo.cleanup import _referenced_files
from repo.models import Repository


def _raise(error):
    raise error


def _relative(raw):
    if not raw or raw.startswith("/") or ".." in raw.split("/") or "\0" in raw:
        raise ValueError(f"Invalid relative path: {raw!r}")
    return Path(raw)


def _href(raw):
    url = urlsplit(raw)
    if url.scheme or url.netloc or url.query or url.fragment:
        raise ValueError(f"Not a local package URL: {raw!r}")
    return _relative(unquote(url.path, errors="strict"))


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a" and "href" in dict(attrs):
            self.links.append(dict(attrs)["href"])


def _metadata(root, path):
    """Never open metadata through a link outside the live generation."""
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"Invalid index: {path}")
    return resolved


def _records(stream, start_key=None):
    record = {}
    for line in stream:
        if not line.strip():
            if record:
                yield record
                record = {}
        elif not line[0].isspace():
            key, value = line.rstrip("\r\n").split(":", 1)
            if key == start_key and record:
                yield record
                record = {}
            if key in record:
                raise ValueError(f"Duplicate index field {key!r}; missing record separator?")
            record[key] = value.lstrip()
    if record:
        yield record


def _entries(repo, root):
    """Yield (relative filesystem path, advertised spelling, hash type, digest)."""
    if repo.repo_type == "deb":
        component = root / "dists/stable/main"
        directories = [p for p in component.iterdir() if p.name.startswith("binary-")]
        if not directories:
            raise ValueError("No published APT architecture indexes")
        for directory in directories:
            available = False
            for name in ("Packages", "Packages.gz"):
                path = directory / name
                if not path.exists():
                    continue
                available = True
                with (gzip.open if name.endswith(".gz") else open)(
                    _metadata(root, path), "rt", encoding="utf-8"
                ) as stream:
                    for row in _records(stream):
                        raw = row["Filename"]
                        yield _relative(raw), raw, "sha256", row["SHA256"]
            if not available:
                raise ValueError(f"No Packages index in {directory}")
    elif repo.repo_type == "rpm":
        arches = {p.name for p in root.iterdir() if not p.is_symlink() and p.is_dir() and p.name != "repodata"}
        if (root / "repodata").exists() or not arches:
            arches.add("")
        for arch in arches:
            base = root / arch
            repomd = ET.parse(_metadata(root, base / "repodata/repomd.xml"))
            primary = repomd.find(".//{*}data[@type='primary']/{*}location")
            if primary is None:
                raise ValueError("Missing primary RPM index")
            path = _metadata(root, base / _href(primary.attrib["href"]))
            with (gzip.open if path.suffix == ".gz" else open)(path, "rb") as stream:
                for _, pkg in ET.iterparse(stream):
                    if pkg.tag.split("}")[-1] == "package":
                        raw = pkg.find("{*}location").attrib["href"]
                        checksum = pkg.find("{*}checksum")
                        yield Path(arch) / _href(raw), raw, checksum.attrib["type"], checksum.text
                        pkg.clear()
    elif repo.repo_type == "files":
        parser = _Links()
        parser.feed(_metadata(root, root / "index.html").read_text(encoding="utf-8"))
        for raw in parser.links:
            yield _href(raw), raw, "", ""
    elif repo.repo_type == "apk":
        with tarfile.open(_metadata(root, root / "APKINDEX.tar.gz"), "r:gz") as archive:
            with TextIOWrapper(archive.extractfile("APKINDEX"), encoding="utf-8") as stream:
                for row in _records(stream, start_key="C"):
                    raw = f"{row['P']}-{row['V']}.apk"
                    # This adapter writes Q1 + base64(SHA1 of the whole file).
                    if not row["C"].startswith("Q1"):
                        raise ValueError("Unknown APK checksum format")
                    yield _relative(raw), raw, "sha1", base64.b64decode(row["C"][2:], validate=True).hex()
    else:
        raise ValueError(f"Unsupported repository type: {repo.repo_type}")


def _hashes(path, algorithms):
    hashes = {name: hashlib.new(name) for name in algorithms}
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            for digest in hashes.values():
                digest.update(chunk)
    return {name: digest.hexdigest() for name, digest in hashes.items()}


def _valid_digest(algorithm, digest):
    if algorithm not in {"sha1", "sha256", "sha512"} or not digest:
        return False
    return bool(re.fullmatch(r"[0-9a-fA-F]+", digest) and len(digest) == 2 * hashlib.new(algorithm).digest_size)


def _name_warnings(name):
    warnings = []
    if "\ufffd" in name or any(unicodedata.category(c) == "Cs" for c in name):
        warnings.append("Replacement character or undecodable filesystem byte")
    if any(unicodedata.category(c) in {"Cc", "Cf"} for c in name):
        warnings.append("Control or invisible formatting character")
    if re.search(r"%[0-9a-fA-F]{2}", name):
        warnings.append("Literal percent escape in filename; verify URL encoding")
    if name != name.strip():
        warnings.append("Leading or trailing whitespace")
    return warnings


def _match_key(name):
    # Used only to suggest spellings for inspection, never to establish file identity.
    return re.sub(r"[ _~-]+", "_", unicodedata.normalize("NFC", unquote(name)))


def audit(stream):
    """Stream all findings as JSON Lines; only a bounded preview goes into Redis."""
    storage = Path(settings.STORAGE_PATH).resolve(strict=True)
    www = Path(settings.REPO_WWW_PATH).resolve(strict=True)
    if (not storage.is_dir() or not www.is_dir()
            or storage.is_relative_to(www) or www.is_relative_to(storage)):
        raise ValueError("Check the worker storage and publish mounts")
    now = time.time()
    counts, preview, missing = Counter(), [], defaultdict(set)
    candidate_bytes = 0

    def finding(kind, path, **detail):
        row = dict(kind=kind, path=str(path), **detail)
        stream.write(json.dumps(row) + "\n")
        counts[kind] += 1
        if len(preview) < 100:
            preview.append(row)

    # Protect all in-flight uploads, even jobs older than the age threshold.
    refs = _referenced_files(datetime.min.replace(tzinfo=timezone.utc), onerror=_raise)
    cached = {}
    repositories = list(Repository.objects.all())
    known = {repo.repo_uid for repo in repositories}
    for entry in www.iterdir():
        if entry.is_symlink() and entry.name not in known:
            finding("Incomplete", entry.name, reason="Unmanaged live link; indexes not verified")
        elif entry.is_dir() and not entry.is_symlink() and entry.name not in known:
            uid, _, generation = entry.name.rpartition(".")
            if not generation.isdigit() or uid not in known:
                finding("Incomplete", entry.name, reason="Unmanaged publish directory; indexes not verified")
    for repo in repositories:
        uid = repo.repo_uid
        try:
            link = www / _relative(uid)
            root = link.resolve(strict=True)
            if root.parent != www or not root.is_dir():
                raise ValueError("Live generation outside publish root")
            indexed = set()
            missing_spellings = defaultdict(list)
            indexed_targets = set()
            seen = set()
            for rel, raw, algorithm, digest in _entries(repo, root):
                if (rel, algorithm, digest) in seen:
                    continue
                seen.add((rel, algorithm, digest))
                indexed.add(rel)
                target = (root / rel).resolve()
                if not (target.is_relative_to(root) or target.is_relative_to(storage)):
                    raise ValueError(f"Package link outside repository/storage: {rel}")
                if algorithm and not _valid_digest(algorithm, digest):
                    raise ValueError(f"Unsupported or missing checksum: {rel}")
                problem = None
                if not target.is_file():
                    problem = "Indexed file missing"
                    missing_spellings[rel.parent, _match_key(rel.name)].append(raw)
                else:
                    indexed_targets.add(target)
                    if target.is_relative_to(storage):
                        refs.add(str(target.relative_to(storage)))
                if not problem and algorithm:
                    key = (target, algorithm)
                    if key not in cached:
                        cached[key] = _hashes(target, [algorithm])[algorithm]
                    if cached[key] != digest.lower():
                        problem = "Indexed checksum mismatch"
                if problem:
                    finding(problem, Path(uid) / rel, advertised=raw, checksum=digest or "")
                    if algorithm:
                        missing[algorithm, digest.lower()].add(str(Path(uid) / rel))
                    else:
                        finding("Incomplete", uid, reason=f"No full checksum for {raw}")
            for folder, _, files in os.walk(root, onerror=_raise):
                for name in files:
                    path = Path(folder) / name
                    rel = path.relative_to(root)
                    if rel in indexed or path.is_symlink() or path.suffix in {".deb", ".rpm", ".apk"}:
                        warnings = _name_warnings(name)
                        similar = missing_spellings.get((rel.parent, _match_key(name)), [])
                        if similar:
                            warnings.append("Similar spelling to a missing indexed path; identity not verified")
                        if warnings:
                            finding("Filename needs review", Path(uid) / rel, reasons=warnings,
                                    advertised=similar, escaped_name=ascii(name))
                        if rel not in indexed:
                            finding("Published but not indexed", Path(uid) / rel)
            fields = ("package_uid", "filename", "checksum_sha256", "checksum_sha512")
            for pkg in repo.package_set.only(*fields).iterator():
                rel = pkg.relative_path()
                if storage / rel not in indexed_targets:
                    finding("Database package not reached by index", rel, repository=uid,
                            filename=pkg.filename, checksum=pkg.checksum_sha256)
                    if not (storage / _relative(rel)).is_file():
                        known_hash = False
                        for algo, value in [("sha256", pkg.checksum_sha256), ("sha512", pkg.checksum_sha512)]:
                            if _valid_digest(algo, value):
                                missing[algo, value.lower()].add(f"{uid}: {pkg.filename}")
                                known_hash = True
                        if not known_hash:
                            finding("Incomplete", rel, reason="Missing database payload with no usable checksum")
            if root != link.resolve(strict=True):
                raise ValueError("Live generation changed during audit")
        except (OSError, ValueError, KeyError, AttributeError, ET.ParseError, tarfile.TarError) as exc:
            finding("Incomplete", uid, reason=str(exc))

    for folder, _, files in os.walk(storage, onerror=_raise):
        for name in files:
            path = Path(folder) / name
            rel = path.relative_to(storage)
            info = path.lstat()
            age = int((now - info.st_mtime) / 3600)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or str(rel) in refs or age < 168):
                continue
            warnings = _name_warnings(name)
            if warnings:
                finding("Filename needs review", rel, reasons=warnings, escaped_name=ascii(name))
            hashes = _hashes(path, {"sha256"} | {algo for algo, _ in missing})
            matches = sorted({p for key in hashes.items() for p in missing.get(key, ())})
            if matches:
                kind = "Possible recovery copy"
            elif counts["Incomplete"] or warnings:
                kind = "Unverified storage file"
            else:
                kind = "Unreferenced storage candidate"
                candidate_bytes += info.st_size
            finding(kind, rel, bytes=info.st_size, age_hours=age, sha256=hashes["sha256"], matches=matches)
    return {"counts": dict(counts), "candidate_bytes": candidate_bytes, "preview": preview}
