"""Master / reference data (dimensions) for the demo company.

All fact tables reference these dimensions by id, so referential integrity is
guaranteed by construction.  Everything is derived from a single seeded
``random.Random`` instance, making the whole dataset reproducible.

The module also computes a :class:`Scenarios` object that pins the specific
ids used by the planted AI-discoverable stories (scrap creep, NRE overrun,
material-cost variance, attrition spike, supplier defect trend, facility
incident trend).  The narrative documents reference the same ids so the data
and the prose stay consistent.
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass, field

from .config import CompanySpec

Row = dict[str, object]

_CITIES = [
    ("Austin", "TX", "US", "Americas"),
    ("Greenville", "SC", "US", "Americas"),
    ("Cedar Rapids", "IA", "US", "Americas"),
    ("Tempe", "AZ", "US", "Americas"),
    ("Querétaro", "QRO", "MX", "Americas"),
    ("Windsor", "ON", "CA", "Americas"),
]

_COMMODITIES = [
    "Machined Castings", "Sheet Metal", "Electronics", "Fasteners",
    "Composites", "Wire Harness", "Bearings", "Seals & Gaskets",
    "Forgings", "Coatings",
]

_CUSTOMERS = [
    "Northwind Aerospace", "Cascade Defense Systems", "Meridian Motors",
    "Vantage Robotics", "Helios Energy", "Atlas Rail", "BlueLark Medical",
    "Ironclad Industrial", "Sterling Marine",
]

_JOB_CLASSES = [
    "Assembler", "CNC Machinist", "Quality Inspector", "Manufacturing Engineer",
    "Design Engineer", "Test Engineer", "Buyer", "Financial Analyst",
    "HR Generalist", "IT Support", "Program Manager", "Account Executive",
    "Maintenance Technician", "EHS Specialist", "Contracts Administrator",
]

_FIRST = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael",
    "Linda", "David", "Elizabeth", "William", "Barbara", "Richard", "Susan",
    "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen", "Priya",
    "Wei", "Diego", "Amara", "Hiroshi", "Fatima", "Lucas", "Sofia",
]
_LAST = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Wilson",
    "Anderson", "Thomas", "Nguyen", "Patel", "Kim", "Okafor", "Rossi",
    "Novak", "Haddad", "Chen", "Silva",
]


@dataclass
class Scenarios:
    """Ids that anchor the planted AI-discoverable stories."""

    scrap_work_center: str = ""
    scrap_site: str = ""
    overrun_projects: list[str] = field(default_factory=list)
    overrun_programs: list[str] = field(default_factory=list)
    material_cost_program: str = ""
    attrition_job_class: str = ""
    attrition_site: str = ""
    defect_supplier_id: str = ""
    defect_supplier_name: str = "Apex Metalworks"
    incident_site: str = ""
    slipping_customer: str = ""


@dataclass
class Dimensions:
    spec: CompanySpec
    rng: random.Random
    sites: list[Row] = field(default_factory=list)
    departments: list[Row] = field(default_factory=list)
    accounts: list[Row] = field(default_factory=list)
    programs: list[Row] = field(default_factory=list)
    work_centers: list[Row] = field(default_factory=list)
    parts: list[Row] = field(default_factory=list)
    employees: list[Row] = field(default_factory=list)
    suppliers: list[Row] = field(default_factory=list)
    contracts: list[Row] = field(default_factory=list)
    eng_projects: list[Row] = field(default_factory=list)
    scenarios: Scenarios = field(default_factory=Scenarios)

    # convenience id lists ------------------------------------------------
    @property
    def site_ids(self) -> list[str]:
        return [s["SiteID"] for s in self.sites]

    @property
    def dept_ids(self) -> list[str]:
        return [d["DeptID"] for d in self.departments]

    @property
    def program_ids(self) -> list[str]:
        return [p["ProgramID"] for p in self.programs]


_FUNCTIONS = [
    "Executive", "Finance", "HR", "Manufacturing", "Engineering", "Sales",
    "Quality", "Procurement", "IT", "EHS", "Legal",
]


def build_dimensions(spec: CompanySpec) -> Dimensions:
    rng = random.Random(spec.seed)
    prof = spec.profile
    dims = Dimensions(spec=spec, rng=rng)

    # Sites ---------------------------------------------------------------
    for i in range(prof.sites):
        city, state, country, region = _CITIES[i % len(_CITIES)]
        dims.sites.append({
            "SiteID": f"SITE-{i + 1:02d}",
            "SiteName": f"{city} Plant",
            "City": city,
            "State": state,
            "Country": country,
            "Region": region,
            "SquareFeet": rng.choice([85000, 120000, 160000, 210000]),
            "OpenedDate": dt.date(2005 + i, rng.randint(1, 12), 1).isoformat(),
        })

    # Functional departments ---------------------------------------------
    for i, fn in enumerate(_FUNCTIONS):
        dims.departments.append({
            "DeptID": f"DEPT-{i + 1:02d}",
            "DeptName": fn,
            "Function": fn,
            "CostCenter": f"CC{1000 + (i + 1) * 10}",
        })

    # GL chart of accounts ------------------------------------------------
    chart = [
        ("4000", "Product Revenue", "Revenue"),
        ("4100", "Service Revenue", "Revenue"),
        ("5000", "Direct Material", "COGS"),
        ("5100", "Direct Labor", "COGS"),
        ("5200", "Manufacturing Overhead", "COGS"),
        ("5300", "Scrap & Rework", "COGS"),
        ("6000", "Engineering Labor", "Opex"),
        ("6100", "Non-Recurring Engineering", "Opex"),
        ("6200", "Sales & Marketing", "Opex"),
        ("6300", "General & Administrative", "Opex"),
        ("6400", "IT & Systems", "Opex"),
        ("6500", "Facilities & EHS", "Opex"),
        ("7000", "Depreciation", "Opex"),
        ("1500", "Capital Equipment", "Asset"),
    ]
    for num, name, atype in chart:
        dims.accounts.append({
            "AccountNumber": num,
            "AccountName": name,
            "AccountType": atype,
            "Category": "Operating" if atype in ("Revenue", "COGS", "Opex") else "Balance Sheet",
        })

    # Programs ------------------------------------------------------------
    for i in range(prof.programs):
        cust = _CUSTOMERS[i % len(_CUSTOMERS)]
        start = dt.date(2023, rng.randint(1, 12), 1)
        dims.programs.append({
            "ProgramID": f"PGM-{i + 1:03d}",
            "ProgramName": f"{cust.split()[0]} {rng.choice(['Falcon', 'Titan', 'Orion', 'Vector', 'Apollo', 'Nova', 'Delta', 'Zephyr', 'Comet'])}",
            "Customer": cust,
            "ProgramType": rng.choice(["Production", "Development", "Aftermarket"]),
            "StartDate": start.isoformat(),
            "Status": rng.choice(["Active", "Active", "Active", "Ramp", "Sunset"]),
            "TargetMarginPct": rng.choice([18, 22, 25, 28, 31]),
        })

    # Work centers --------------------------------------------------------
    processes = ["Machining", "Welding", "Assembly", "Coating", "Inspection",
                 "Heat Treat", "Fabrication", "Test", "Kitting"]
    wc_idx = 0
    for s in dims.sites:
        for j in range(max(2, prof.work_centers // prof.sites)):
            wc_idx += 1
            proc = processes[(wc_idx - 1) % len(processes)]
            dims.work_centers.append({
                "WorkCenterID": f"WC-{wc_idx:03d}",
                "WorkCenterName": f"Line {j + 1} {proc}",
                "SiteID": s["SiteID"],
                "Process": proc,
                "Shifts": rng.choice([1, 2, 2, 3]),
            })

    # Suppliers -----------------------------------------------------------
    supplier_names = [
        "Apex Metalworks", "Cardinal Components", "Delta Forge", "Evergreen Alloys",
        "Frontier Fasteners", "Granite Precision", "Harbor Electronics",
        "Ironwood Composites", "Juniper Coatings", "Keystone Bearings",
        "Lakeside Seals", "Monarch Machining", "Northstar Wire", "Orchard Plastics",
        "Pinnacle Castings", "Quartz Sensors", "Redwood Rubber", "Summit Sheetmetal",
        "Titan Tooling", "Vertex Valves",
    ]
    for i in range(prof.suppliers):
        name = supplier_names[i] if i < len(supplier_names) else f"Supplier {i + 1:03d} LLC"
        _, _, country, _ = _CITIES[i % len(_CITIES)]
        dims.suppliers.append({
            "SupplierID": f"SUP-{i + 1:03d}",
            "SupplierName": name,
            "Commodity": _COMMODITIES[i % len(_COMMODITIES)],
            "Country": country,
            "OnboardedDate": dt.date(2018 + (i % 7), rng.randint(1, 12), 1).isoformat(),
            "RiskTier": rng.choice(["Low", "Low", "Medium", "Medium", "High"]),
        })

    # Parts ---------------------------------------------------------------
    for i in range(prof.parts):
        prog = dims.programs[i % len(dims.programs)]
        sup = dims.suppliers[i % len(dims.suppliers)]
        dims.parts.append({
            "PartID": f"PN-{10000 + i}",
            "PartName": f"{_COMMODITIES[i % len(_COMMODITIES)].split()[0]} {rng.choice(['Bracket', 'Housing', 'Shaft', 'Panel', 'Cover', 'Manifold', 'Ring', 'Plate'])} R{rng.randint(1, 5)}",
            "Commodity": _COMMODITIES[i % len(_COMMODITIES)],
            "ProgramID": prog["ProgramID"],
            "PrimarySupplierID": sup["SupplierID"],
            "StandardCostUSD": round(rng.uniform(12, 850), 2),
            "UOM": "EA",
        })

    # Engineering projects ------------------------------------------------
    for i in range(prof.eng_projects):
        prog = dims.programs[i % len(dims.programs)]
        dims.eng_projects.append({
            "ProjectID": f"EPRJ-{i + 1:03d}",
            "ProjectName": f"{prog['ProgramName']} {rng.choice(['Redesign', 'Qualification', 'Cost-Down', 'Line Transfer', 'Automation'])}",
            "ProgramID": prog["ProgramID"],
            "Phase": rng.choice(["Concept", "Design", "Validation", "Production"]),
            "BudgetUSD": rng.choice([250000, 400000, 650000, 900000, 1200000]),
            "Status": rng.choice(["Active", "Active", "Active", "On Hold", "Closed"]),
        })

    # Contracts -----------------------------------------------------------
    for i in range(prof.contracts):
        is_customer = i % 2 == 0
        party = (_CUSTOMERS[i % len(_CUSTOMERS)] if is_customer
                 else supplier_names[i % len(supplier_names)])
        start = dt.date(2022 + (i % 4), rng.randint(1, 12), 1)
        dims.contracts.append({
            "ContractID": f"CTR-{i + 1:04d}",
            "CounterParty": party,
            "ContractType": "Customer" if is_customer else "Supplier",
            "Category": rng.choice(["Master Supply", "NDA", "Statement of Work",
                                    "License", "Services"]),
            "ValueUSD": rng.choice([50000, 150000, 500000, 1500000, 4000000]),
            "StartDate": start.isoformat(),
            "EndDate": (start + dt.timedelta(days=365 * rng.randint(1, 4))).isoformat(),
            "Status": rng.choice(["Active", "Active", "Active", "Expiring", "Renewal"]),
        })

    _build_employees(dims, rng)
    _pin_scenarios(dims, rng)
    return dims


def _build_employees(dims: Dimensions, rng: random.Random) -> None:
    prof = dims.spec.profile
    managers: list[str] = []
    for i in range(prof.employees):
        emp_id = f"EMP-{100000 + i}"
        dept = dims.departments[i % len(dims.departments)]
        site = dims.sites[i % len(dims.sites)]
        job = _JOB_CLASSES[i % len(_JOB_CLASSES)]
        hire = dt.date(2016, 1, 1) + dt.timedelta(days=rng.randint(0, 365 * 10))
        # Roughly 12% have left; termination dates roll through 2026.
        terminated = rng.random() < 0.12
        term = None
        status = "Active"
        if terminated:
            term_dt = hire + dt.timedelta(days=rng.randint(400, 365 * 8))
            if term_dt > dt.date(2026, 7, 6):
                term_dt = dt.date(2026, rng.randint(1, 7), rng.randint(1, 28))
            term = term_dt.isoformat()
            status = "Terminated"
        mgr = rng.choice(managers) if managers and rng.random() < 0.9 else ""
        salary = {
            "Assembler": 52000, "CNC Machinist": 61000, "Quality Inspector": 58000,
            "Manufacturing Engineer": 92000, "Design Engineer": 104000,
            "Test Engineer": 98000, "Buyer": 72000, "Financial Analyst": 84000,
            "HR Generalist": 70000, "IT Support": 66000, "Program Manager": 128000,
            "Account Executive": 96000, "Maintenance Technician": 63000,
            "EHS Specialist": 74000, "Contracts Administrator": 79000,
        }.get(job, 70000)
        salary = int(salary * rng.uniform(0.9, 1.18))
        dims.employees.append({
            "EmployeeID": emp_id,
            "FullName": f"{rng.choice(_FIRST)} {rng.choice(_LAST)}",
            "DeptID": dept["DeptID"],
            "SiteID": site["SiteID"],
            "JobClass": job,
            "HireDate": hire.isoformat(),
            "Status": status,
            "TerminationDate": term or "",
            "ManagerID": mgr,
            "AnnualSalaryUSD": salary,
        })
        if job in ("Program Manager", "Manufacturing Engineer") and len(managers) < 30:
            managers.append(emp_id)


def _pin_scenarios(dims: Dimensions, rng: random.Random) -> None:
    sc = dims.scenarios
    # Scrap creep: pick a "Line 2" work center at the second site if present.
    line2 = [w for w in dims.work_centers if "Line 2" in str(w["WorkCenterName"])]
    hot = line2[0] if line2 else dims.work_centers[min(1, len(dims.work_centers) - 1)]
    sc.scrap_work_center = str(hot["WorkCenterID"])
    sc.scrap_site = str(hot["SiteID"])
    # Engineering overrun projects → EPRJ-003 and EPRJ-007 (per business_ops docs).
    ids = {e["ProjectID"] for e in dims.eng_projects}
    sc.overrun_projects = [p for p in ("EPRJ-003", "EPRJ-007") if p in ids]
    if not sc.overrun_projects:
        sc.overrun_projects = [str(dims.eng_projects[0]["ProjectID"])]
    sc.overrun_programs = sorted({
        str(e["ProgramID"]) for e in dims.eng_projects
        if e["ProjectID"] in set(sc.overrun_projects)
    })
    # Material-cost variance program: the first overrun program (ties finance
    # variance to engineering + procurement stories).
    sc.material_cost_program = sc.overrun_programs[0] if sc.overrun_programs else str(dims.programs[1]["ProgramID"])
    # Attrition spike: CNC Machinist at the scrap site.
    sc.attrition_job_class = "CNC Machinist"
    sc.attrition_site = sc.scrap_site
    # Supplier defect trend: Apex Metalworks (or first supplier).
    apex = [s for s in dims.suppliers if s["SupplierName"] == "Apex Metalworks"]
    sc.defect_supplier_id = str((apex[0] if apex else dims.suppliers[0])["SupplierID"])
    sc.defect_supplier_name = str((apex[0] if apex else dims.suppliers[0])["SupplierName"])
    # Facility incident trend: the scrap site (concentrates the operational story).
    sc.incident_site = sc.scrap_site
    # Sales slippage: a customer tied to the material-cost program.
    prog = [p for p in dims.programs if p["ProgramID"] == sc.material_cost_program]
    sc.slipping_customer = str((prog[0] if prog else dims.programs[0])["Customer"])
