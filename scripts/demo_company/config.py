"""Configuration for the Demo Company Installer.

Defines the company specification (name, industry, size, seed), the calendar
window that all generated data is rolled forward to, and the department →
Tablescope-project structure.  Nothing here talks to a database or an API; it
is pure configuration consumed by the generators, the manifest builder and the
importer.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

# ── Calendar ────────────────────────────────────────────────────────────
# Per issue #15 the demo "current date" is 2026-07-06.  Monthly tables run
# through the current month (2026-07-01); weekly tables through the most recent
# completed Monday on/before the current date (2026-07-06 is a Monday).
CURRENT_DATE = dt.date(2026, 7, 6)
MONTHLY_THROUGH = dt.date(2026, 7, 1)
WEEKLY_THROUGH = dt.date(2026, 7, 6)

# History windows.
MONTHLY_START = dt.date(2024, 1, 1)
WEEKLY_START = dt.date(2025, 1, 6)  # first Monday of 2025
# Budget / forecast horizon: FY2026 budget + rolling forecast through FY2027.
BUDGET_START = dt.date(2026, 1, 1)
FORECAST_THROUGH = dt.date(2027, 12, 1)


# ── Company specification ───────────────────────────────────────────────
@dataclass(frozen=True)
class SizeProfile:
    """Scale knobs derived from the requested company ``size``."""

    employees: int
    sites: int
    programs: int
    parts: int
    work_centers: int
    suppliers: int
    contracts: int
    eng_projects: int


SIZE_PROFILES: dict[str, SizeProfile] = {
    "Startup": SizeProfile(60, 1, 3, 40, 4, 12, 8, 4),
    "SMB": SizeProfile(180, 2, 5, 90, 6, 25, 20, 6),
    "MidMarket": SizeProfile(420, 3, 7, 160, 9, 45, 40, 9),
    "Enterprise": SizeProfile(820, 4, 9, 260, 12, 70, 65, 12),
}


@dataclass(frozen=True)
class CompanySpec:
    """Everything needed to generate and load one synthetic company."""

    company: str = "Simplicit"
    display_name: str = "Simplicit Demo Company"
    industry: str = "Manufacturing"
    size: str = "Enterprise"
    seed: int = 42

    @property
    def profile(self) -> SizeProfile:
        return SIZE_PROFILES[self.size]

    @property
    def slug(self) -> str:
        return self.company.strip().lower().replace(" ", "-")


# ── Department → project structure ──────────────────────────────────────
# Tablescope projects are flat (no nesting), so every department is its own
# project.  Company-wide policies and procedures are NOT projects — they live
# in the platform's Company Library (Reference Library, company tier).  Executive
# review packages are documents belonging to the Executive project.
@dataclass(frozen=True)
class Department:
    key: str  # short code used in output folder names
    project: str  # Tablescope project name
    description: str


DEPARTMENTS: list[Department] = [
    Department("Executive", "Executive",
               "Enterprise KPIs, risk register, decisions and action items."),
    Department("Finance", "Finance",
               "General ledger, budgets, forecasts and indirect rates."),
    Department("HR", "HR",
               "Employees, headcount plan, attrition and performance."),
    Department("Manufacturing", "Manufacturing",
               "Shop-floor labor, scrap, material and capacity."),
    Department("Engineering", "Engineering",
               "Engineering labor, project budgets and NRE watchlists."),
    Department("Sales", "Sales",
               "Revenue, programs, pipeline, bookings and backlog."),
    Department("Quality", "Quality",
               "Nonconformances, CAPA, supplier scorecards and audits."),
    Department("Procurement", "Procurement",
               "Supplier master, purchase orders and supply risk."),
    Department("IT", "IT",
               "Assets, incidents, change requests and access requests."),
    Department("EHS", "EHS",
               "Safety incidents, training records and audit findings."),
    Department("Legal_Contracts", "Legal & Contracts",
               "Contracts master, obligations and disputes."),
]

# Company Library (Reference Library, company tier) — where policies and
# procedures go instead of being their own projects.  Documents are tagged with
# one of the platform's known domain tags, mapped from the owning department.
COMPANY_LIBRARY = "Company Library"

LIBRARY_DOMAIN_BY_DEPT: dict[str, str] = {
    "Executive": "Other",
    "Finance": "Finance & Accounting",
    "HR": "HR",
    "Manufacturing": "Manufacturing & Quality",
    "Engineering": "Engineering & Product",
    "Sales": "Marketing & Sales",
    "Quality": "Manufacturing & Quality",
    "Procurement": "Supply Chain & Procurement",
    "IT": "IT & Cybersecurity",
    "EHS": "ESG",
    "Legal": "Legal & Compliance",
    "Legal_Contracts": "Legal & Compliance",
}


def library_domain(department: str) -> str:
    return LIBRARY_DOMAIN_BY_DEPT.get(department, "Other")


def all_projects(spec: CompanySpec) -> list[Department]:
    """Every Tablescope project the installer will create, in order."""
    return list(DEPARTMENTS)


# ── Calendar helpers ────────────────────────────────────────────────────
def month_starts(start: dt.date, through: dt.date) -> list[dt.date]:
    """First-of-month dates from ``start`` through ``through`` inclusive."""
    out: list[dt.date] = []
    y, m = start.year, start.month
    while (y, m) <= (through.year, through.month):
        out.append(dt.date(y, m, 1))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def week_mondays(start: dt.date, through: dt.date) -> list[dt.date]:
    """Monday dates from ``start`` (a Monday) through ``through`` inclusive."""
    d = start - dt.timedelta(days=start.weekday())
    out: list[dt.date] = []
    while d <= through:
        out.append(d)
        d += dt.timedelta(days=7)
    return out


def fiscal_period(d: dt.date) -> str:
    return f"{d.year}-{d.month:02d}"


def quarter_of(d: dt.date) -> str:
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
