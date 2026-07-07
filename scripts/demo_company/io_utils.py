"""Small IO helpers shared by the generators.

Provides a deterministic CSV writer and an :class:`Artifact` registry that
records every generated file with the metadata the manifest builder and the
importer need (department, destination project, artifact type, tags, row
count, and a short description).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Artifact:
    """One generated file plus its destination metadata."""

    rel_path: str  # path relative to the company output root
    department: str  # short department key
    project: str  # Tablescope project name
    artifact_type: str  # e.g. "Operational Data", "Policy", "Budget"
    kind: str  # "csv" or "document"
    tags: list[str] = field(default_factory=list)
    rows: int = 0
    description: str = ""
    date_range: str = ""


class Registry:
    """Collects artifacts and writes CSV/text files under a root directory."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.artifacts: list[Artifact] = []

    def _abs(self, rel_path: str) -> Path:
        p = self.root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def write_csv(
        self,
        rel_path: str,
        fieldnames: list[str],
        rows: list[dict[str, object]],
        *,
        department: str,
        project: str,
        artifact_type: str,
        tags: list[str],
        description: str = "",
        date_range: str = "",
    ) -> Artifact:
        abs_path = self._abs(rel_path)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})
        abs_path.write_text(buf.getvalue(), encoding="utf-8")
        art = Artifact(
            rel_path=rel_path, department=department, project=project,
            artifact_type=artifact_type, kind="csv", tags=tags,
            rows=len(rows), description=description, date_range=date_range,
        )
        self.artifacts.append(art)
        return art

    def write_text(
        self,
        rel_path: str,
        text: str,
        *,
        department: str,
        project: str,
        artifact_type: str,
        tags: list[str],
        description: str = "",
    ) -> Artifact:
        abs_path = self._abs(rel_path)
        abs_path.write_text(text, encoding="utf-8")
        art = Artifact(
            rel_path=rel_path, department=department, project=project,
            artifact_type=artifact_type, kind="document", tags=tags,
            rows=0, description=description,
        )
        self.artifacts.append(art)
        return art

    # ── reporting helpers ────────────────────────────────────────────
    def csv_artifacts(self) -> list[Artifact]:
        return [a for a in self.artifacts if a.kind == "csv"]

    def doc_artifacts(self) -> list[Artifact]:
        return [a for a in self.artifacts if a.kind == "document"]
