"""Unit tests for DemoImporter.

These tests use a fake API client so they run without a running server.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

from demo_company.importer import ApiClient, DemoImporter, compute_view_name  # noqa: E402


@dataclass
class _FakeCall:
    method: str
    path: str
    kwargs: dict = field(default_factory=dict)


class FakeApiClient(ApiClient):
    """Records requests and returns canned responses."""

    def __init__(self) -> None:  # noqa: D107
        # Deliberately skip ApiClient.__init__; no real network state needed.
        self.base = "http://fake"
        self.timeout = 180.0
        self.calls: list[_FakeCall] = []
        self.projects: list[dict] = []
        self.datasources: list[dict] = []
        self.library: list[dict] = []
        self.project_assets: dict[int, list[dict]] = {}

    def get(self, path: str):
        self.calls.append(_FakeCall("GET", path))
        if path == "/api/projects":
            return self.projects
        if path.startswith("/api/upload/datasources"):
            return self.datasources
        if path.startswith("/api/reference-library/documents"):
            return self.library
        if path.startswith("/api/projects/") and "/assets" in path:
            try:
                pid = int(path.split("/")[3])
            except (IndexError, ValueError):
                pid = 0
            return self.project_assets.get(pid, [])
        return None

    def post_json(self, path: str, payload: dict):
        self.calls.append(_FakeCall("POST", path, {"payload": payload}))
        if path == "/api/projects":
            pid = len(self.projects) + 1
            self.projects.append({"id": pid, "name": payload["name"]})
            return {"id": pid, "name": payload["name"]}
        return {}

    def put_json(self, path: str, payload: dict):
        self.calls.append(_FakeCall("PUT", path, {"payload": payload}))
        return {}

    def post_multipart(self, path: str, *, fields: dict[str, str],
                       file_field: str, filename: str, file_bytes: bytes,
                       content_type: str):
        self.calls.append(
            _FakeCall(
                "POST",
                path,
                {
                    "fields": fields,
                    "file_field": file_field,
                    "filename": filename,
                    "content_type": content_type,
                    "size": len(file_bytes),
                },
            )
        )
        return {"status": "ok"}


def _write_csv(root: Path, rel: str, rows: int = 3) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        f.write("A,B\n")
        for i in range(rows):
            f.write(f"{i},{i * 10}\n")


def _manifest(project_names: list[str], artifact_rels: list[str]) -> dict:
    return {
        "company": "FakeCo",
        "projects": [{"name": n, "description": ""} for n in project_names],
        "artifacts": [
            {
                "path": rel,
                "kind": "csv",
                "department": "Finance",
                "target": "project",
                "destination_project": project_names[i % len(project_names)],
                "artifact_type": "Operational Data",
                "tags": [],
            }
            for i, rel in enumerate(artifact_rels)
        ],
    }


def test_refresh_false_skips_existing_data_source(tmp_path):
    client = FakeApiClient()
    client.projects = [{"id": 1, "name": "Finance"}]
    view = compute_view_name("finance_ledger.csv")
    client.datasources = [{"viewName": view}]

    rel = "data/Finance/finance_ledger.csv"
    _write_csv(tmp_path, rel)
    manifest = _manifest(["Finance"], [rel])

    importer = DemoImporter(client, manifest, tmp_path, refresh=False)
    report = importer.run()

    assert report.skipped == 1
    assert report.created == 0
    assert report.replaced == 0
    assert not any(c.path == "/api/upload" for c in client.calls)
    assert not any("/replace" in c.path for c in client.calls)


def test_refresh_true_replaces_existing_data_source(tmp_path):
    client = FakeApiClient()
    client.projects = [{"id": 1, "name": "Finance"}]
    view = compute_view_name("finance_ledger.csv")
    client.datasources = [{"viewName": view}]

    rel = "data/Finance/finance_ledger.csv"
    _write_csv(tmp_path, rel)
    manifest = _manifest(["Finance"], [rel])

    importer = DemoImporter(client, manifest, tmp_path, refresh=True)
    report = importer.run()

    assert report.replaced == 1
    assert report.skipped == 0
    assert report.created == 0
    replace_calls = [c for c in client.calls if "/replace" in c.path]
    assert len(replace_calls) == 1
    assert replace_calls[0].path == f"/api/upload/datasources/{view}/replace"
    assert not any(c.path == "/api/upload" for c in client.calls)


def test_refresh_true_uploads_new_data_source(tmp_path):
    client = FakeApiClient()
    client.projects = [{"id": 1, "name": "Finance"}]
    client.datasources = []  # nothing exists yet

    rel = "data/Finance/finance_ledger.csv"
    _write_csv(tmp_path, rel)
    manifest = _manifest(["Finance"], [rel])

    importer = DemoImporter(client, manifest, tmp_path, refresh=True)
    report = importer.run()

    assert report.created == 1
    assert report.replaced == 0
    assert report.skipped == 0
    assert any(c.path == "/api/upload" for c in client.calls)
    assert not any("/replace" in c.path for c in client.calls)


def test_dry_run_refresh_true_shows_replace_not_upload(tmp_path, capsys):
    client = FakeApiClient()
    client.projects = [{"id": 1, "name": "Finance"}]
    view = compute_view_name("finance_ledger.csv")
    client.datasources = [{"viewName": view}]

    rel = "data/Finance/finance_ledger.csv"
    _write_csv(tmp_path, rel)
    manifest = _manifest(["Finance"], [rel])

    importer = DemoImporter(
        client, manifest, tmp_path, dry_run=True, refresh=True
    )
    report = importer.run()

    assert report.created == 1
    assert report.replaced == 0
    assert not any("/replace" in c.path for c in client.calls)
    assert not any(c.path == "/api/upload" for c in client.calls)
    captured = capsys.readouterr()
    assert "would replace CSV" in captured.out


def test_refresh_does_not_affect_documents_or_library(tmp_path):
    client = FakeApiClient()
    client.projects = [{"id": 1, "name": "Finance"}]
    client.library = [{"title": "Some Policy"}]
    client.project_assets = {1: [{"original_filename": "some_policy.md"}]}

    rel_csv = "data/Finance/finance_ledger.csv"
    rel_doc = "docs/Finance/some_policy.md"
    _write_csv(tmp_path, rel_csv)
    (tmp_path / rel_doc).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / rel_doc).write_text("# Policy", encoding="utf-8")

    manifest = {
        "company": "FakeCo",
        "projects": [{"name": "Finance", "description": ""}],
        "artifacts": [
            {
                "path": rel_csv,
                "kind": "csv",
                "department": "Finance",
                "target": "project",
                "destination_project": "Finance",
                "artifact_type": "Operational Data",
                "tags": [],
            },
            {
                "path": rel_doc,
                "kind": "doc",
                "department": "Finance",
                "target": "project",
                "destination_project": "Finance",
                "artifact_type": "Policy",
                "tags": [],
            },
        ],
    }

    importer = DemoImporter(client, manifest, tmp_path, refresh=True)
    report = importer.run()

    # CSV is new (no existing view) so it uploads normally.
    assert report.created == 1
    # Document should still be skipped because the filename already exists.
    assert report.skipped == 1
    assert report.replaced == 0
    doc_calls = [c for c in client.calls if "/assets/upload" in c.path]
    assert not doc_calls
