"""Validation tests for the Demo Company Installer generators.

Runnable with::

    python -m pytest scripts/tests/test_demo_company.py

Covers reproducibility, calendar coverage, referential integrity and the
presence of the planted AI-discoverable scenarios. These generators live under
``scripts/`` (not the platform-api / ai-server packages), so they are not part
of those services' CI test suites; run this module directly to validate output.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

from demo_company import config as C  # noqa: E402
from demo_company.datasets import generate_datasets  # noqa: E402
from demo_company.dimensions import build_dimensions  # noqa: E402
from demo_company.documents import generate_documents  # noqa: E402
from demo_company.io_utils import Registry  # noqa: E402
from demo_company.manifest import build_manifest, load_manifest  # noqa: E402


def _generate(tmp: Path) -> tuple[Registry, object]:
    spec = C.CompanySpec()
    dims = build_dimensions(spec)
    reg = Registry(tmp)
    generate_datasets(reg, dims)
    return reg, dims


def _read(root: Path, rel: str) -> list[dict]:
    with (root / rel).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_reproducible(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    _generate(a)
    _generate(b)
    files = sorted(p.relative_to(a) for p in a.rglob("*.csv"))
    assert files, "no CSVs generated"
    for rel in files:
        assert (a / rel).read_bytes() == (b / rel).read_bytes(), f"non-deterministic: {rel}"


def test_calendar_coverage(tmp_path):
    reg, _ = _generate(tmp_path)
    gl = _read(tmp_path, "data/Finance/fin_gl_monthly.csv")
    assert max(r["Month"] for r in gl) == C.MONTHLY_THROUGH.isoformat()
    scrap = _read(tmp_path, "data/Manufacturing/mfg_scrap_weekly.csv")
    week_col = "WeekStart" if "WeekStart" in scrap[0] else list(scrap[0])[0]
    assert max(r[week_col] for r in scrap) == C.WEEKLY_THROUGH.isoformat()


def test_referential_integrity(tmp_path):
    reg, dims = _generate(tmp_path)
    dept_ids = {d["DeptID"] for d in dims.departments}
    site_ids = {s["SiteID"] for s in dims.sites}
    prog_ids = set(dims.program_ids)

    scrap = _read(tmp_path, "data/Manufacturing/mfg_scrap_weekly.csv")
    assert {r["SiteID"] for r in scrap} <= site_ids
    attr = _read(tmp_path, "data/HR/hr_attrition_risk.csv")
    assert {r["DeptID"] for r in attr} <= dept_ids
    assert {r["SiteID"] for r in attr} <= site_ids
    eng = _read(tmp_path, "data/Engineering/eng_labor_actuals_monthly.csv")
    assert {r["ProgramID"] for r in eng} <= prog_ids


def test_planted_scenarios(tmp_path):
    reg, dims = _generate(tmp_path)
    sc = dims.scenarios

    # Scrap creep: pinned work center's rate rises over time.
    scrap = [r for r in _read(tmp_path, "data/Manufacturing/mfg_scrap_weekly.csv")
             if r["WorkCenterID"] == sc.scrap_work_center]
    rate_col = "ScrapPct" if "ScrapPct" in scrap[0] else "ScrapPercent"
    assert float(scrap[-1][rate_col]) > float(scrap[0][rate_col]) + 1.0

    # NRE overrun: pinned projects flagged.
    watch = {r["ProjectID"]: r for r in
             _read(tmp_path, "data/Engineering/eng_nre_overrun_watchlist.csv")}
    for pid in sc.overrun_projects:
        assert watch[pid]["Status"] == "Overrun"

    # Supplier defect: pinned supplier has elevated PPM.
    scards = {r["SupplierID"]: r for r in
              _read(tmp_path, "data/Quality/quality_supplier_scorecards.csv")}
    assert float(scards[sc.defect_supplier_id]["DefectPPM"]) > 2000


def test_policies_procedures_go_to_company_library(tmp_path):
    spec = C.CompanySpec()
    dims = build_dimensions(spec)
    reg = Registry(tmp_path)
    generate_datasets(reg, dims)
    generate_documents(reg, dims)
    build_manifest(reg, spec, "owner@example.com")
    man = load_manifest(tmp_path / "manifest.yaml")

    project_names = {p["name"] for p in man["projects"]}
    # The doc-only projects no longer exist.
    assert "Policies" not in project_names
    assert "Procedures" not in project_names
    assert "Executive Reviews" not in project_names
    assert "Executive" in project_names

    by_type: dict[str, set[str]] = {}
    for a in man["artifacts"]:
        by_type.setdefault(a["artifact_type"], set()).add(a.get("target"))

    # Policies and procedures target the Company Library; everything else a project.
    assert by_type["Policy"] == {"library"}
    assert by_type["Procedure"] == {"library"}
    assert by_type["Monthly Review"] == {"project"}
    assert by_type["Quarterly Review"] == {"project"}

    lib = [a for a in man["artifacts"] if a.get("target") == "library"]
    assert lib, "no library artifacts"
    for a in lib:
        assert a["destination_project"] == C.COMPANY_LIBRARY
        assert a["domain_tag"] in C.LIBRARY_DOMAIN_BY_DEPT.values()

    # Executive reviews are documents in the Executive project.
    reviews = [a for a in man["artifacts"]
               if a["artifact_type"] in ("Monthly Review", "Quarterly Review")]
    assert reviews and all(a["destination_project"] == "Executive" for a in reviews)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
