"""Generate the human-facing documentation for the demo company.

Builds ``README.md``, ``data_dictionary.md``, ``documents_dictionary.md`` and
``answer_key.md`` from the registry of generated artifacts, so the docs always
match the actual output (row counts, date ranges, file lists) and describe the
planted AI-discoverable scenarios.
"""

from __future__ import annotations

import csv
from pathlib import Path

from . import config as C
from .dimensions import Dimensions
from .io_utils import Registry


def _read_header(root: Path, rel_path: str) -> list[str]:
    p = root / rel_path
    with p.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        return next(reader, [])


def generate_docs(reg: Registry, dims: Dimensions) -> None:
    _readme(reg, dims)
    _data_dictionary(reg, dims)
    _documents_dictionary(reg, dims)
    _answer_key(reg, dims)


def _readme(reg: Registry, dims: Dimensions) -> None:
    spec = dims.spec
    csvs = reg.csv_artifacts()
    docs = reg.doc_artifacts()
    total_rows = sum(a.rows for a in csvs)
    body = f"""# {spec.display_name}

A complete synthetic demo company for Tablescope: structured datasets plus
unstructured business documents spanning every department. Everything is
generated from seeded pseudo-random data and is fully reproducible.

> All names, financials, employees, suppliers, and documents are fictional and
> for demonstration only.

## Profile
- **Company:** {spec.display_name}
- **Industry:** {spec.industry}
- **Size:** {spec.size} (~{spec.profile.employees} employees, {spec.profile.sites} sites)
- **Seed:** {spec.seed}

## Contents
- **{len(csvs)} CSV datasets** ({total_rows:,} rows) under `data/<Department>/`
- **{len(docs)} documents** under `docs/` (policies, procedures, executive
  reviews, and department business reports)

## Date Coverage
- Monthly tables run through **{C.MONTHLY_THROUGH.isoformat()}**.
- Weekly tables run through **{C.WEEKLY_THROUGH.isoformat()}**.
- Budget / forecast tables run through **{C.FORECAST_THROUGH.isoformat()}**.

## Regenerate
```bash
python scripts/install_demo_company.py --company {spec.company} \\
    --industry {spec.industry} --size {spec.size} --seed {spec.seed} \\
    --generate-only
```

## Load into Tablescope
```bash
# Preview without calling the API
python scripts/install_demo_company.py --dry-run

# Small sample first, then everything (needs API base URL + owner credentials)
python scripts/install_demo_company.py --sample
python scripts/install_demo_company.py --all
```
The loader creates one Tablescope project per department (owned by the
configured user), uploads each CSV as a data source (which auto-creates a
saved query and triggers AI processing), and uploads each document as an
AI-processed business asset. It is idempotent and prints a summary report.

## Documentation
- `data_dictionary.md` — every dataset, its columns, row count and date range.
- `documents_dictionary.md` — every policy / procedure / review / report.
- `answer_key.md` — the planted AI-discoverable scenarios and how to find them.
"""
    reg.write_text("README.md", body, department="Executive", project="Executive",
                   artifact_type="Documentation", tags=["readme"],
                   description="Demo company README.")


def _data_dictionary(reg: Registry, dims: Dimensions) -> None:
    lines = [f"# {dims.spec.display_name} — Data Dictionary\n",
             "Auto-generated from the produced CSV files.\n"]
    by_dept: dict[str, list] = {}
    for a in reg.csv_artifacts():
        by_dept.setdefault(a.department, []).append(a)
    for dept in sorted(by_dept):
        lines.append(f"## {dept}\n")
        for a in sorted(by_dept[dept], key=lambda x: x.rel_path):
            header = _read_header(reg.root, a.rel_path)
            lines.append(f"### `{a.rel_path}`")
            lines.append(f"- **Type:** {a.artifact_type}")
            lines.append(f"- **Rows:** {a.rows:,}")
            if a.date_range:
                lines.append(f"- **Date range:** {a.date_range}")
            lines.append(f"- **Description:** {a.description}")
            lines.append(f"- **Columns:** {', '.join(header)}")
            if a.tags:
                lines.append(f"- **Tags:** {', '.join(a.tags)}")
            lines.append("")
    reg.write_text("data_dictionary.md", "\n".join(lines),
                   department="Executive", project="Executive",
                   artifact_type="Documentation", tags=["data-dictionary"],
                   description="Data dictionary for all datasets.")


def _documents_dictionary(reg: Registry, dims: Dimensions) -> None:
    lines = [f"# {dims.spec.display_name} — Documents Dictionary\n",
             "Auto-generated from the produced documents.\n"]
    by_type: dict[str, list] = {}
    for a in reg.doc_artifacts():
        by_type.setdefault(a.artifact_type, []).append(a)
    for atype in sorted(by_type):
        lines.append(f"## {atype}\n")
        for a in sorted(by_type[atype], key=lambda x: x.rel_path):
            lines.append(f"- `{a.rel_path}` — {a.description} "
                         f"(project: {a.project}; tags: {', '.join(a.tags)})")
        lines.append("")
    reg.write_text("documents_dictionary.md", "\n".join(lines),
                   department="Executive", project="Executive",
                   artifact_type="Documentation", tags=["documents-dictionary"],
                   description="Dictionary of all documents.")


def _answer_key(reg: Registry, dims: Dimensions) -> None:
    sc = dims.scenarios
    lines = [
        f"# {dims.spec.display_name} — Answer Key (Planted Scenarios)\n",
        "These are the AI-discoverable stories seeded into the data and "
        "documents. Each is internally consistent across departments so "
        "Tablescope can demonstrate cross-department analytics and document "
        "intelligence.\n",
        "## 1. Finance — material-cost budget variance",
        f"- Program **{sc.material_cost_program}** shows rising material cost from "
        "2025-10 onward.",
        "- Data: `data/Manufacturing/mfg_material_actuals_monthly.csv`, "
        "`data/Finance/fin_budget_vs_actual_monthly.csv`, "
        "`data/Procurement/procurement_material_price_history.csv`.",
        "- Docs: `FIN-001`, `FIN-003`.\n",
        "## 2. Manufacturing — scrap creep",
        f"- Work center **{sc.scrap_work_center}** at site **{sc.scrap_site}** shows "
        "scrap % climbing through H1 2026.",
        "- Data: `data/Manufacturing/mfg_scrap_weekly.csv`, "
        "`data/Quality/quality_defect_trends_monthly.csv`.",
        "- Docs: `MFG-001`.\n",
        "## 3. Engineering — NRE overrun",
        f"- Projects **{', '.join(sc.overrun_projects)}** (programs "
        f"{', '.join(sc.overrun_programs)}) exceed budget ~28%.",
        "- Data: `data/Engineering/eng_nre_overrun_watchlist.csv`, "
        "`data/Engineering/eng_labor_actuals_monthly.csv`.",
        "- Docs: `ENG-001`.\n",
        "## 4. HR — attrition spike",
        f"- **{sc.attrition_job_class}** at site **{sc.attrition_site}** shows high "
        "attrition risk.",
        "- Data: `data/HR/hr_attrition_risk.csv`.",
        "- Docs: `HR-001`, `HR-002`.\n",
        "## 5. Quality — supplier defect trend",
        f"- Supplier **{sc.defect_supplier_name}** ({sc.defect_supplier_id}) has "
        "elevated defect PPM, linked to manufacturing scrap.",
        "- Data: `data/Quality/quality_supplier_scorecards.csv`, "
        "`data/Quality/quality_nonconformance_log.csv`.",
        "- Docs: `QA-002`.\n",
        "## 6. IT — onboarding access delay",
        "- A cohort of new hires has long access-grant times.",
        "- Data: `data/IT/it_access_requests.csv`, `data/HR/hr_onboarding_status.csv`.",
        "- Docs: `IT-002`, `HR-004`.\n",
        "## 7. EHS — facility incident trend",
        f"- Incidents concentrate at site **{sc.incident_site}**.",
        "- Data: `data/EHS/ehs_incidents.csv`.",
        "- Docs: `EHS-001`, `EHS-002`.\n",
        "## 8. Sales — forecast slippage",
        f"- Customer **{sc.slipping_customer}** opportunities slip; revenue dips in "
        "H1 2026.",
        "- Data: `data/Sales/sales_pipeline_forecast.csv`, "
        "`data/Sales/sales_revenue_monthly.csv`.",
        "- Docs: `SAL-002`.\n",
        "## 9. Executive — overdue action items",
        "- Action items in the **Operational** category are repeatedly overdue.",
        "- Data: `data/Executive/action_items.csv`, "
        "`data/Executive/enterprise_risk_register.csv`.",
        "- Docs: `EXEC-001`.\n",
    ]
    reg.write_text("answer_key.md", "\n".join(lines),
                   department="Executive", project="Executive",
                   artifact_type="Documentation", tags=["answer-key"],
                   description="Planted scenario answer key.")
