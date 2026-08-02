"""Manifest-driven importer for the demo company.

Reads the manifest and, authenticated as the demo owner, creates one Tablescope
project per department, uploads each CSV as a data source (which auto-creates a
saved query and triggers AI processing) and each document as an AI-processed
project asset. Idempotent (skips artifacts that already exist), supports
dry-run and sample modes, and prints a created/updated/skipped/failed report.

Uses only the standard library (urllib) so it can run anywhere without pip
installs.
"""

from __future__ import annotations

import json
import mimetypes
import re
import ssl
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

_RESERVED = re.compile(r"[\\/:*?\"<>|$,]")
_MULTI_US = re.compile(r"_{2,}")
_TRIM_US = re.compile(r"^_+|_+$")


def compute_view_name(filename: str) -> str:
    """Mirror of the backend's Teiid view-name derivation (for idempotency)."""
    base, _, ext = filename.rpartition(".") if "." in filename else (filename, "", "")
    base = _RESERVED.sub("_", base).replace(" ", "_")
    base = _TRIM_US.sub("", _MULTI_US.sub("_", base)) or "file"
    return f"{base}_{ext.upper()}" if ext else base


# ── HTTP client ────────────────────────────────────────────────────────────
class ApiError(RuntimeError):
    pass


class ApiClient:
    def __init__(self, base_url: str, *, token: str | None = None,
                 insecure: bool = False, timeout: float = 180.0) -> None:
        self.base = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._ctx = ssl._create_unverified_context() if insecure else None

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if extra:
            h.update(extra)
        return h

    def _request(self, method: str, path: str, *, data: bytes | None = None,
                 headers: dict | None = None):
        url = path if path.startswith("http") else f"{self.base}{path}"
        if not url.startswith("http"):
            raise ApiError(f"{method} {url} → no base URL configured")
        req = urllib.request.Request(url, data=data, method=method,
                                     headers=self._headers(headers))
        try:
            with urllib.request.urlopen(req, timeout=self.timeout,
                                        context=self._ctx) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            raise ApiError(f"{method} {url} → {e.code}: {body[:500]}") from None
        except urllib.error.URLError as e:
            raise ApiError(f"{method} {url} → connection error: {e.reason}") from None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw.decode("utf-8", "replace")}

    def get(self, path: str):
        return self._request("GET", path)

    def post_json(self, path: str, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        return self._request("POST", path, data=data,
                             headers={"Content-Type": "application/json"})

    def put_json(self, path: str, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        return self._request("PUT", path, data=data,
                             headers={"Content-Type": "application/json"})

    def post_multipart(self, path: str, *, fields: dict[str, str],
                       file_field: str, filename: str, file_bytes: bytes,
                       content_type: str):
        boundary = f"----demo{uuid.uuid4().hex}"
        body = bytearray()
        for k, v in fields.items():
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode()
            body += f"{v}\r\n".encode()
        body += f"--{boundary}\r\n".encode()
        body += (f'Content-Disposition: form-data; name="{file_field}"; '
                 f'filename="{filename}"\r\n').encode()
        body += f"Content-Type: {content_type}\r\n\r\n".encode()
        body += file_bytes + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        return self._request(
            "POST", path, data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})

    def login(self, email: str, password: str) -> str:
        res = self.post_json("/api/auth/login", {"email": email, "password": password})
        token = (res or {}).get("access_token")
        if not token:
            raise ApiError(f"Login did not return a token: {res}")
        self.token = token
        return token


# ── Report ─────────────────────────────────────────────────────────────────
@dataclass
class Report:
    projects_created: int = 0
    projects_existing: int = 0
    created: int = 0
    replaced: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "── Demo Company Import Report ──",
            f"Projects: {self.projects_created} created, {self.projects_existing} existing",
            f"Artifacts: {self.created} uploaded, {self.replaced} replaced, "
            f"{self.skipped} skipped, {self.failed} failed",
        ]
        for f in self.failures:
            lines.append(f"  ! {f}")
        return "\n".join(lines)


# ── Importer ─────────────────────────────────────────────────────────────
class DemoImporter:
    def __init__(self, client: ApiClient, manifest: dict, root: Path, *,
                 dry_run: bool = False, sample: bool = False,
                 shared: bool = True, verbose: bool = True,
                 refresh: bool = False) -> None:
        self.c = client
        self.m = manifest
        self.root = root
        self.dry_run = dry_run
        self.sample = sample
        self.shared = shared
        self.verbose = verbose
        self.refresh = refresh
        self.report = Report()
        self._projects: dict[str, int] = {}
        self._datasource_views: set[str] = set()
        self._assets_by_project: dict[int, set[str]] = {}
        self._library_titles: set[str] = set()

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    # -- projects ---------------------------------------------------------
    def ensure_projects(self) -> None:
        existing: dict[str, int] = {}
        if not self.dry_run:
            for p in (self.c.get("/api/projects") or []):
                existing[p["name"]] = p["id"]
        for proj in self.m.get("projects", []):
            name = proj["name"]
            if name in existing:
                self._projects[name] = existing[name]
                self.report.projects_existing += 1
                self._log(f"  = project exists: {name} (id={existing[name]})")
                continue
            if self.dry_run:
                self._log(f"  + would create project: {name}")
                self._projects[name] = -1
                self.report.projects_created += 1
                continue
            created = self.c.post_json("/api/projects", {
                "name": name, "description": proj.get("description", ""),
                "type": "department"})
            pid = created["id"]
            if self.shared:
                try:
                    self.c.put_json(f"/api/projects/{pid}", {"is_shared": True})
                except ApiError:
                    pass
            self._projects[name] = pid
            self.report.projects_created += 1
            self._log(f"  + created project: {name} (id={pid})")

    # -- idempotency caches ----------------------------------------------
    def _load_existing(self) -> None:
        try:
            for ds in (self.c.get("/api/upload/datasources?include_archived=true") or []):
                if isinstance(ds, dict) and ds.get("viewName"):
                    self._datasource_views.add(ds["viewName"])
        except ApiError:
            pass
        try:
            res = self.c.get("/api/reference-library/documents?tier=company")
            if isinstance(res, dict):
                docs = res.get("documents") or res.get("items")
            else:
                docs = res
            for d in docs or []:
                if isinstance(d, dict) and d.get("title"):
                    self._library_titles.add(str(d["title"]).strip().lower())
        except ApiError:
            pass

    def _assets_for(self, pid: int) -> set[str]:
        if pid in self._assets_by_project:
            return self._assets_by_project[pid]
        names: set[str] = set()
        if not self.dry_run and pid > 0:
            try:
                for a in (self.c.get(f"/api/projects/{pid}/assets") or []):
                    if isinstance(a, dict):
                        for key in ("original_filename", "filename", "title"):
                            if a.get(key):
                                names.add(str(a[key]))
            except ApiError:
                pass
        self._assets_by_project[pid] = names
        return names

    # -- run --------------------------------------------------------------
    def run(self) -> Report:
        self._log("Ensuring projects…")
        self.ensure_projects()
        self._load_existing()
        arts = self.m.get("artifacts", [])
        if self.sample:
            arts = [a for a in arts if a.get("sample")]
        self._log(f"Processing {len(arts)} artifact(s)"
                  f"{' (sample)' if self.sample else ''}…")
        for a in arts:
            try:
                self._process(a)
            except ApiError as e:
                self.report.failed += 1
                self.report.failures.append(f"{a.get('path')}: {e}")
                self._log(f"  ! failed: {a.get('path')}: {e}")
        if self.refresh and not self.dry_run:
            self._reprocess_ai()
        return self.report

    def _reprocess_ai(self) -> None:
        """Refresh AI-derived content for the affected projects and home snapshot."""
        pids = {pid for pid in self._projects.values() if pid and pid > 0}
        if not pids:
            return
        # AI refresh endpoints can run for several minutes; raise the timeout.
        original_timeout = self.c.timeout
        self.c.timeout = max(self.c.timeout, 1200.0)
        try:
            self._log("Reprocessing AI content for affected projects…")
            for pid in sorted(pids):
                try:
                    resp = self.c.post_json(f"/api/projects/{pid}/graph/refresh", {})
                    node_count = (resp or {}).get("nodeCount", "?")
                    self._log(f"  ~ refreshed project {pid} graph "
                              f"({node_count} nodes)")
                except ApiError as e:
                    self._log(f"  ! project {pid} graph refresh failed: {e}")
            try:
                self._log("  ~ refreshing home intelligence snapshot…")
                resp = self.c.get("/api/home-intelligence/stream?cross_project=true")
                raw = (resp or {}).get("raw", "")
                if '"type": "done"' in raw or "'type': 'done'" in raw:
                    self._log("  ~ home intelligence snapshot refreshed.")
                else:
                    self._log("  ! home intelligence stream did not signal completion")
            except ApiError as e:
                self._log(f"  ! home intelligence refresh failed: {e}")
        finally:
            self.c.timeout = original_timeout

    def _process(self, a: dict) -> None:
        rel = a["path"]
        if a.get("target") == "library":
            path = self.root / rel
            if not path.exists():
                self.report.failed += 1
                self.report.failures.append(f"{rel}: file not found")
                return
            self._upload_library(a, path, path.name)
            return
        proj_name = a["destination_project"]
        pid = self._projects.get(proj_name)
        if pid is None:
            self.report.failed += 1
            self.report.failures.append(f"{rel}: no project '{proj_name}'")
            return
        path = self.root / rel
        if not path.exists():
            self.report.failed += 1
            self.report.failures.append(f"{rel}: file not found")
            return
        filename = path.name
        if a.get("kind") == "csv":
            self._upload_csv(a, pid, path, filename)
        else:
            self._upload_doc(a, pid, path, filename)

    def _doc_title(self, path: Path) -> str:
        return path.stem.replace("_", " ").replace("-", " ").title()

    def _refresh_library_titles(self) -> None:
        try:
            res = self.c.get("/api/reference-library/documents?tier=company")
            if isinstance(res, dict):
                docs = res.get("documents") or res.get("items")
            else:
                docs = res
            for d in docs or []:
                if isinstance(d, dict) and d.get("title"):
                    self._library_titles.add(str(d["title"]).strip().lower())
        except ApiError:
            pass

    def _upload_library(self, a: dict, path: Path, filename: str) -> None:
        title = self._doc_title(path)
        if title.lower() in self._library_titles:
            self.report.skipped += 1
            self._log(f"  = skip (in library): {a['path']}")
            return
        if self.dry_run:
            self.report.created += 1
            self._log(f"  + would upload → Company Library: {a['path']}")
            return
        ctype = mimetypes.guess_type(filename)[0] or "text/markdown"
        try:
            self.c.post_multipart(
                "/api/reference-library/documents",
                fields={"tier": "company", "title": title,
                        "domain_tag": a.get("domain_tag") or "Other",
                        "applicability_tag": "Company-specific"},
                file_field="file", filename=filename,
                file_bytes=path.read_bytes(), content_type=ctype)
        except ApiError as e:
            msg = str(e)
            if "→ 409" in msg or ": 409" in msg:
                self._library_titles.add(title.lower())
                self.report.skipped += 1
                self._log(f"  = skip (duplicate in library): {a['path']}")
                return
            # The reference-library create endpoint can persist the document and
            # still return 5xx (a background-processing error surfaces after the
            # DB commit). Verify by title before treating it as a real failure.
            if "→ 5" in msg or ": 5" in msg:
                self._refresh_library_titles()
                if title.lower() in self._library_titles:
                    self.report.created += 1
                    self._log(f"  + uploaded → Company Library: {a['path']}"
                              " (saved; server returned 5xx during AI processing)")
                    return
            raise
        self._library_titles.add(title.lower())
        self.report.created += 1
        self._log(f"  + uploaded → Company Library: {a['path']} (AI processing)")

    def _upload_csv(self, a: dict, pid: int, path: Path, filename: str) -> None:
        view = compute_view_name(filename)
        exists = view in self._datasource_views
        if exists and not self.refresh:
            self.report.skipped += 1
            self._log(f"  = skip (exists): {a['path']}")
            return
        if self.dry_run:
            verb = "replace" if exists else "upload"
            self.report.created += 1
            self._log(f"  + would {verb} CSV → {a['destination_project']}: {a['path']}")
            return
        if exists:
            self.c.post_multipart(
                f"/api/upload/datasources/{view}/replace",
                fields={}, file_field="file", filename=filename,
                file_bytes=path.read_bytes(), content_type="text/csv")
            self.report.replaced += 1
            self._log(f"  ~ replaced CSV → {a['destination_project']}: {a['path']}")
            return
        self.c.post_multipart(
            "/api/upload",
            fields={"project_id": str(pid), "vdb_type": "user"},
            file_field="file", filename=filename,
            file_bytes=path.read_bytes(), content_type="text/csv")
        self._datasource_views.add(view)
        self.report.created += 1
        self._log(f"  + uploaded CSV → {a['destination_project']}: {a['path']}"
                  " (data source + query + AI)")

    def _upload_doc(self, a: dict, pid: int, path: Path, filename: str) -> None:
        existing = self._assets_for(pid)
        if filename in existing:
            self.report.skipped += 1
            self._log(f"  = skip (exists): {a['path']}")
            return
        if self.dry_run:
            self.report.created += 1
            self._log(f"  + would upload doc → {a['destination_project']}: {a['path']}")
            return
        ctype = mimetypes.guess_type(filename)[0] or "text/markdown"
        tags = a.get("tags") or []
        desc = a.get("description", "")
        if tags:
            desc = (desc + f" [tags: {', '.join(tags)}]").strip()
        self.c.post_multipart(
            f"/api/projects/{pid}/assets/upload",
            fields={"asset_type": _asset_type(a, filename),
                    "title": path.stem.replace("_", " ").replace("-", " ").title(),
                    "description": desc, "visibility": "shared_project"},
            file_field="file", filename=filename,
            file_bytes=path.read_bytes(), content_type=ctype)
        existing.add(filename)
        self.report.created += 1
        self._log(f"  + uploaded doc → {a['destination_project']}: {a['path']} (AI processing)")


def _asset_type(a: dict, filename: str) -> str:
    at = str(a.get("artifact_type", "")).lower()
    if "policy" in at:
        return "policy"
    if "procedure" in at:
        return "procedure"
    if "review" in at:
        return "review"
    if "report" in at:
        return "report"
    return "markdown"
