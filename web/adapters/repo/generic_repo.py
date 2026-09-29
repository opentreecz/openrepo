# Copyright 2022 by Open Kilt LLC. All rights reserved.
# This file is part of the OpenRepo Repository Management Software (OpenRepo)
# OpenRepo is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License
# version 3 as published by the Free Software Foundation
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import hashlib
import html
import logging
import os
import subprocess

from django.conf import settings

from .base_repo import BaseRepoAdapter

logger = logging.getLogger("openrepo_web")


class GenericRepoAdapter(BaseRepoAdapter):
    def _get_repo_instructions(self):
        return f"{self.base_url}"

    def _generate_repo_structure(self, repo_path):

        # Symlink all files in the repo
        self._copy_packages(repo_path)

        # Generate MD5 checksum files for each package
        self._generate_md5_files(repo_path)

        # Build a searchable HTML index page
        self._generate_html_index(repo_path)

        # PGP signing (if a signing key is configured)
        if self.pgp_key is not None:
            self._sign_index(repo_path)
            self._save_public_key(repo_path)

        return True

    def _generate_md5_files(self, repo_path):
        """Generate a .md5 checksum file for each package in the repo."""
        with self._buildlog_section("Generating MD5 checksums") as log_entry:
            count = 0
            for entry in os.scandir(repo_path):
                if not entry.is_file(follow_symlinks=True):
                    continue
                # Skip metadata files we generate ourselves
                if entry.name.endswith(".md5") or entry.name in ("index.html", "index.html.asc", "public.gpg"):
                    continue
                md5 = _file_md5(entry.path)
                md5_path = os.path.join(repo_path, f"{entry.name}.md5")
                with open(md5_path, "w") as f:
                    f.write(f"{md5}  {entry.name}\n")
                count += 1
            log_entry.set_message(f"Generated {count} .md5 checksum file(s)")

    def _generate_html_index(self, repo_path):
        """Generate a single-page HTML index listing all packages with metadata."""
        rows = []
        for pkg in self.packages.order_by("package_name", "-upload_date"):
            src_path = os.path.join(settings.STORAGE_PATH, pkg.relative_path())
            try:
                size = os.path.getsize(src_path)
            except OSError:
                size = 0

            ext = os.path.splitext(pkg.filename)[1]
            pool_name = f"{pkg.package_name}_{pkg.version}_{pkg.architecture}{ext}"

            rows.append(
                _html_row(
                    filename=pool_name,
                    package_name=pkg.package_name,
                    version=pkg.version,
                    architecture=pkg.architecture,
                    size=size,
                    upload_date=pkg.upload_date.strftime("%Y-%m-%d %H:%M") if pkg.upload_date else "",
                    sha512=pkg.checksum_sha512 or "",
                )
            )

        index_path = os.path.join(repo_path, "index.html")
        with open(index_path, "w") as f:
            f.write(_html_page(self.repo_uid, rows))

        with self._buildlog_section("Generating HTML index") as log_entry:
            log_entry.set_message(f"Generated index.html with {len(rows)} package(s)")

    def _sign_index(self, repo_path):
        """Create a detached GPG signature for index.html."""
        index_path = os.path.join(repo_path, "index.html")
        sig_path = os.path.join(repo_path, "index.html.asc")

        if not os.path.isfile(index_path):
            return

        custom_env = os.environ.copy()
        custom_env["GNUPGHOME"] = settings.KEYRING_PATH

        with self._buildlog_section("Signing index.html") as log_entry:
            try:
                result = subprocess.run(
                    [
                        "gpg",
                        "--batch",
                        "--yes",
                        "--armor",
                        "--detach-sign",
                        "--default-key", self.pgp_key.fingerprint,
                        "--output", sig_path,
                        index_path,
                    ],
                    env=custom_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=self.SUBPROCESS_TIMEOUT,
                )
                if result.returncode == 0:
                    log_entry.set_message("Created index.html.asc (detached signature)")
                else:
                    log_entry.set_message(f"GPG signing failed: {result.stdout}")
                    log_entry.set_loglevel(self.BUILDLOG_WARNING)
            except subprocess.TimeoutExpired:
                log_entry.set_message(f"GPG signing timed out after {self.SUBPROCESS_TIMEOUT}s")
                log_entry.set_loglevel(self.BUILDLOG_ERROR)
            except FileNotFoundError:
                log_entry.set_message("gpg binary not found — skipping index signing")
                log_entry.set_loglevel(self.BUILDLOG_WARNING)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file_md5(filepath):
    """Compute the MD5 hex digest of a file, following symlinks."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _esc(text):
    """HTML-escape a string."""
    return html.escape(str(text))


def _human_size(nbytes):
    """Format a byte count as a human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}" if unit != "B" else f"{nbytes} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} PB"


def _html_row(filename, package_name, version, architecture, size, upload_date, sha512):
    """Render a single table row."""
    return (
        f"<tr>"
        f'<td><a href="{_esc(filename)}">{_esc(filename)}</a></td>'
        f"<td>{_esc(package_name)}</td>"
        f"<td>{_esc(version)}</td>"
        f"<td>{_esc(architecture)}</td>"
        f"<td>{_human_size(size)}</td>"
        f"<td>{_esc(upload_date)}</td>"
        f'<td class="sha">{_esc(sha512[:16])}…</td>'
        f"</tr>"
    )


def _html_page(repo_uid, rows):
    """Render the full HTML index page."""
    rows_html = "\n".join(rows) if rows else '<tr><td colspan="7">No packages</td></tr>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenRepo — {_esc(repo_uid)}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         color: #333; background: #fafafa; padding: 1.5rem; }}
  h1 {{ margin-bottom: .5rem; font-size: 1.4rem; }}
  .meta {{ color: #666; font-size: .85rem; margin-bottom: 1rem; }}
  input {{ width: 100%; max-width: 400px; padding: .5rem; margin-bottom: 1rem;
           border: 1px solid #ccc; border-radius: 4px; font-size: .9rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .85rem; }}
  th, td {{ text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #e0e0e0; }}
  th {{ background: #f0f0f0; position: sticky; top: 0; cursor: pointer; }}
  th:hover {{ background: #e0e0e0; }}
  tr:hover {{ background: #f5f5f5; }}
  a {{ color: #0366d6; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .sha {{ font-family: monospace; font-size: .75rem; color: #888; }}
  .hidden {{ display: none; }}
</style>
</head>
<body>
<h1>Repository: {_esc(repo_uid)}</h1>
<p class="meta">{len(rows)} package(s)</p>
<input type="text" id="filter" placeholder="Search packages..." autofocus>
<table>
<thead>
<tr>
  <th>Filename</th><th>Package</th><th>Version</th>
  <th>Arch</th><th>Size</th><th>Uploaded</th><th>SHA-512</th>
</tr>
</thead>
<tbody id="pkg-table">
{rows_html}
</tbody>
</table>
<script>
document.getElementById("filter").addEventListener("input", function() {{
  var q = this.value.toLowerCase();
  var rows = document.querySelectorAll("#pkg-table tr");
  rows.forEach(function(row) {{
    row.classList.toggle("hidden", row.textContent.toLowerCase().indexOf(q) === -1);
  }});
}});
</script>
</body>
</html>
"""
