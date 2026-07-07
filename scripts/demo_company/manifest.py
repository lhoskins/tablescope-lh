"""Build and load the demo-company manifest.

The manifest maps every generated artifact to its destination Tablescope
project plus metadata (department, artifact type, tags, row count, date range).
The importer reads it so upload logic is data-driven rather than hard-coded.

Written as YAML (human-readable, matches issue #15). Loading prefers PyYAML but
falls back to a small parser that understands this manifest's simple structure,
so the tool has no third-party dependency.
"""

from __future__ import annotations

from pathlib import Path

from .config import COMPANY_LIBRARY, CompanySpec, all_projects, library_domain
from .io_utils import Registry

# Artifact types that belong in the Company Library (Reference Library, company
# tier) rather than a project.
LIBRARY_TYPES = {"Policy", "Procedure"}

# Sample subset (Phase 3 of issue #15): a few CSVs + a couple of documents.
SAMPLE_PATHS = {
    "data/Finance/fin_gl_monthly.csv",
    "data/Finance/fin_budget_monthly.csv",
    "data/Sales/sales_revenue_monthly.csv",
    "data/Manufacturing/mfg_scrap_weekly.csv",
    "docs/policies/code_of_conduct.md",
    "docs/executive/monthly_reviews/2026-06_executive_monthly_review.md",
}


def _yaml_quote(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_manifest(reg: Registry, spec: CompanySpec, owner_email: str) -> str:
    projects = all_projects(spec)
    lines: list[str] = [
        f"company: {_yaml_quote(spec.display_name)}",
        f"root_project: {_yaml_quote(spec.display_name)}",
        f"owner_email: {_yaml_quote(owner_email)}",
        f"industry: {_yaml_quote(spec.industry)}",
        f"size: {_yaml_quote(spec.size)}",
        f"seed: {spec.seed}",
        "projects:",
    ]
    for d in projects:
        lines.append(f"  - name: {_yaml_quote(d.project)}")
        lines.append(f"    key: {_yaml_quote(d.key)}")
        lines.append(f"    description: {_yaml_quote(d.description)}")
    lines.append("artifacts:")
    for a in reg.artifacts:
        if a.artifact_type == "Documentation":
            continue  # README / dictionaries / answer key stay on disk only
        is_library = a.artifact_type in LIBRARY_TYPES
        lines.append(f"  - path: {_yaml_quote(a.rel_path)}")
        lines.append(f"    kind: {a.kind}")
        lines.append(f"    department: {_yaml_quote(a.department)}")
        lines.append(f"    target: {'library' if is_library else 'project'}")
        dest = COMPANY_LIBRARY if is_library else a.project
        lines.append(f"    destination_project: {_yaml_quote(dest)}")
        if is_library:
            lines.append(f"    domain_tag: {_yaml_quote(library_domain(a.department))}")
        lines.append(f"    artifact_type: {_yaml_quote(a.artifact_type)}")
        lines.append(f"    tags: [{', '.join(_yaml_quote(t) for t in a.tags)}]")
        lines.append(f"    rows: {a.rows}")
        if a.date_range:
            lines.append(f"    date_range: {_yaml_quote(a.date_range)}")
        if a.description:
            lines.append(f"    description: {_yaml_quote(a.description)}")
        lines.append(f"    sample: {'true' if a.rel_path in SAMPLE_PATHS else 'false'}")
    text = "\n".join(lines) + "\n"
    (reg.root / "manifest.yaml").write_text(text, encoding="utf-8")
    return text


# ── Loading ────────────────────────────────────────────────────────────────
def load_manifest(path: Path) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except Exception:
        return _fallback_parse(text)


def _coerce(val: str):
    v = val.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_coerce(x) for x in _split_list(inner)]
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if v in ("true", "false"):
        return v == "true"
    try:
        return int(v)
    except ValueError:
        return v


def _split_list(inner: str) -> list[str]:
    out, buf, in_q = [], [], False
    for ch in inner:
        if ch == '"':
            in_q = not in_q
            buf.append(ch)
        elif ch == "," and not in_q:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


def _fallback_parse(text: str) -> dict:
    """Minimal parser for the manifest structure this module emits."""
    data: dict = {"projects": [], "artifacts": []}
    cur_list: list | None = None
    cur_item: dict | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        if indent == 0 and line.endswith(":") and line[:-1] in ("projects", "artifacts"):
            cur_list = data[line[:-1]]
            cur_item = None
            continue
        if indent == 0 and ":" in line:
            key, _, val = line.partition(":")
            data[key.strip()] = _coerce(val)
            cur_list = None
            continue
        if cur_list is not None:
            if line.startswith("- "):
                cur_item = {}
                cur_list.append(cur_item)
                line = line[2:]
            if cur_item is not None and ":" in line:
                key, _, val = line.partition(":")
                cur_item[key.strip()] = _coerce(val)
    return data
