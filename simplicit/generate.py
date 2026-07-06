"""
Simplicit Demo Company — synthetic dataset generator.
Run from the simplicit/ directory: python generate.py
Seed = 42 for full reproducibility.
"""

import csv
import os
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)

BASE = Path(__file__).parent
DATA = BASE / "data"

# ── helpers ──────────────────────────────────────────────────────────────────

def months_between(start: date, end: date):
    """Return list of first-of-month dates from start through end (inclusive)."""
    result = []
    d = date(start.year, start.month, 1)
    while d <= date(end.year, end.month, 1):
        result.append(d)
        if d.month == 12:
            d = date(d.year + 1, 1, 1)
        else:
            d = date(d.year, d.month + 1, 1)
    return result

def weeks_ending(start: date, end: date):
    """Return list of week-ending Sundays from start through end."""
    d = start + timedelta(days=(6 - start.weekday()))  # first Sunday >= start
    result = []
    while d <= end:
        result.append(d)
        d += timedelta(weeks=1)
    return result

def fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")

def write_csv(path: Path, fieldnames: list, rows: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {path.relative_to(BASE)} ({len(rows)} rows)")

def rnd(lo, hi, decimals=2):
    return round(random.uniform(lo, hi), decimals)

def jitter(base, pct=0.05):
    return base * (1 + random.uniform(-pct, pct))

# ── reference data ────────────────────────────────────────────────────────────

DEPTS = ["Engineering", "Finance", "HR", "IT", "Manufacturing", "Procurement", "Quality", "Sales", "EHS", "Executive"]

DEPT_HEADCOUNT = {
    "Engineering": 42, "Finance": 18, "HR": 12, "IT": 15,
    "Manufacturing": 160, "Procurement": 14, "Quality": 22,
    "Sales": 28, "EHS": 6, "Executive": 3,
}

LOCATIONS = ["Columbus HQ", "Plant A - Columbus", "Plant B - Dayton"]

FIRST_NAMES = ["James","Maria","David","Sarah","Michael","Jennifer","Robert","Linda","William","Patricia",
               "John","Barbara","Richard","Susan","Thomas","Jessica","Charles","Karen","Christopher","Nancy",
               "Daniel","Lisa","Matthew","Betty","Anthony","Margaret","Mark","Sandra","Donald","Ashley",
               "Steven","Dorothy","Paul","Kimberly","Andrew","Emily","Kenneth","Donna","Joshua","Michelle",
               "Kevin","Carol","Brian","Amanda","George","Melissa","Edward","Deborah","Ronald","Stephanie"]
LAST_NAMES = ["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis","Rodriguez","Martinez",
              "Hernandez","Lopez","Gonzalez","Wilson","Anderson","Thomas","Taylor","Moore","Jackson","Martin",
              "Lee","Perez","Thompson","White","Harris","Sanchez","Clark","Ramirez","Lewis","Robinson",
              "Walker","Young","Allen","King","Wright","Scott","Torres","Nguyen","Hill","Flores",
              "Green","Adams","Nelson","Baker","Hall","Rivera","Campbell","Mitchell","Carter","Roberts"]

PRODUCT_IDS = [f"P{i:03d}" for i in range(1, 16)]
PRODUCT_LINES = ["Aerospace", "Automotive", "Industrial", "Defense", "Medical"]
PRODUCT_LINE_MAP = {p: PRODUCT_LINES[i % 5] for i, p in enumerate(PRODUCT_IDS)}

PART_IDS = [f"PT{i:04d}" for i in range(1, 81)]
LINE_IDS = ["L1", "L2", "L3", "L4"]

SUPPLIER_IDS = [f"SUP{i:03d}" for i in range(1, 26)]

CUSTOMER_IDS = [f"CUS{i:03d}" for i in range(1, 51)]

# ── name pool (deterministic) ─────────────────────────────────────────────────

_name_pool = []
_used_names = set()

def _gen_name():
    while True:
        n = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
        if n not in _used_names:
            _used_names.add(n)
            return n

# ── HR ────────────────────────────────────────────────────────────────────────

def gen_employees():
    rows = []
    emp_id = 1000
    managers = {}  # dept -> list of manager emp_ids

    # Salary bands by dept
    bands = {
        "Engineering": (75000, 140000), "Finance": (65000, 120000),
        "HR": (55000, 100000), "IT": (65000, 125000),
        "Manufacturing": (42000, 90000), "Procurement": (58000, 110000),
        "Quality": (60000, 105000), "Sales": (60000, 130000),
        "EHS": (58000, 100000), "Executive": (120000, 250000),
    }

    dept_location = {
        "Engineering": "Columbus HQ", "Finance": "Columbus HQ",
        "HR": "Columbus HQ", "IT": "Columbus HQ",
        "Manufacturing": None,  # split between plants
        "Procurement": "Columbus HQ", "Quality": None,
        "Sales": "Columbus HQ", "EHS": None, "Executive": "Columbus HQ",
    }

    for dept, count in DEPT_HEADCOUNT.items():
        lo, hi = bands[dept]
        dept_mgrs = []
        for i in range(count):
            eid = f"E{emp_id}"
            name = _gen_name()
            hire_year = random.randint(2015, 2025)
            hire_month = random.randint(1, 12)
            hire_day = random.randint(1, 28)
            hire_date = date(hire_year, hire_month, hire_day)

            # Attrition spike: bump terminations in Q1 2026 and June 2026
            status = "Active"
            if hire_date < date(2023, 1, 1) and random.random() < 0.03:
                # baseline pre-existing terminations
                status = "Terminated"
            elif date(2026, 1, 1) <= hire_date <= date(2026, 3, 31) and random.random() < 0.25:
                status = "Terminated"  # Q1 2026 spike
            elif date(2026, 6, 1) <= hire_date <= date(2026, 6, 30) and random.random() < 0.30:
                status = "Terminated"  # June 2026 spike

            salary = round(random.uniform(lo, hi), -2)
            if dept == "Executive":
                title = random.choice(["CEO", "CFO", "COO", "VP Operations", "VP Sales"])
            elif i == 0:
                title = f"{dept} Director"
                dept_mgrs.append(eid)
            elif i < 4:
                title = f"{dept} Manager"
                dept_mgrs.append(eid)
            else:
                title = random.choice([f"{dept} Specialist", f"{dept} Analyst", f"Sr {dept} Associate", f"{dept} Coordinator"])

            if dept_location[dept]:
                loc = dept_location[dept]
            elif dept == "Manufacturing":
                loc = random.choice(["Plant A - Columbus", "Plant B - Dayton"])
            elif dept == "Quality":
                loc = random.choice(["Plant A - Columbus", "Plant B - Dayton", "Columbus HQ"])
            else:
                loc = random.choice(LOCATIONS)

            mgr_id = ""
            if dept_mgrs and i > 0:
                mgr_id = random.choice(dept_mgrs[:min(4, len(dept_mgrs))])

            rows.append({
                "emp_id": eid, "name": name, "dept": dept, "title": title,
                "hire_date": fmt(hire_date), "status": status,
                "salary": salary, "manager_id": mgr_id, "location": loc,
            })
            emp_id += 1

        managers[dept] = dept_mgrs

    write_csv(DATA / "hr/employees.csv",
              ["emp_id","name","dept","title","hire_date","status","salary","manager_id","location"], rows)
    return rows

def gen_headcount_monthly(employees):
    months = months_between(date(2023, 1, 1), date(2026, 7, 1))
    rows = []
    for dept in DEPTS:
        dept_emps = [e for e in employees if e["dept"] == dept]
        base = len(dept_emps)
        for m in months:
            # Slight growth 2023-2025, dip in 2026
            factor = 1.0
            if m.year == 2023:
                factor = 0.90
            elif m.year == 2024:
                factor = 0.95
            elif m.year == 2025:
                factor = 1.0
            elif m >= date(2026, 1, 1):
                factor = 0.97  # attrition impact
            count = max(1, round(base * factor + random.randint(-1, 1)))
            rows.append({"month": fmt(m), "dept": dept, "headcount": count})
    write_csv(DATA / "hr/headcount_monthly.csv", ["month","dept","headcount"], rows)

def gen_turnover_monthly(employees):
    months = months_between(date(2023, 1, 1), date(2026, 7, 1))
    rows = []
    for dept in DEPTS:
        dept_emps = [e for e in employees if e["dept"] == dept]
        base_hc = len(dept_emps)
        for m in months:
            # Base monthly turnover ~1-2%
            base_rate = random.uniform(0.008, 0.02)
            # Attrition spikes
            if date(2026, 1, 1) <= m <= date(2026, 3, 1):
                base_rate *= random.uniform(1.8, 2.5)
            elif m == date(2026, 6, 1):
                base_rate *= random.uniform(2.0, 3.0)
            count = max(0, round(base_hc * base_rate))
            rate = round(count / max(base_hc, 1) * 100, 2)
            rows.append({"month": fmt(m), "dept": dept, "turnover_count": count, "turnover_rate_pct": rate})
    write_csv(DATA / "hr/turnover_monthly.csv", ["month","dept","turnover_count","turnover_rate_pct"], rows)

def gen_compensation_bands():
    rows = []
    bands_def = [
        ("G1","Manufacturing Associate",35000,42000,52000),
        ("G2","Manufacturing Technician",42000,52000,65000),
        ("G3","Senior Technician / Specialist",55000,67000,82000),
        ("G4","Team Lead / Coordinator",65000,80000,98000),
        ("G5","Manager / Analyst",78000,95000,118000),
        ("G6","Senior Manager / Senior Analyst",95000,118000,145000),
        ("G7","Director",118000,145000,180000),
        ("G8","VP / Executive",150000,200000,270000),
    ]
    for grade, title, lo, mid, hi in bands_def:
        rows.append({"grade":grade,"title":title,"salary_min":lo,"salary_mid":mid,"salary_max":hi})
    write_csv(DATA / "hr/compensation_bands.csv", ["grade","title","salary_min","salary_mid","salary_max"], rows)

def gen_training_completions(employees):
    courses = [
        ("EHS-001","Safety Fundamentals",0,100),
        ("EHS-002","Forklift Certification",60,100),
        ("HR-001","Anti-Harassment Training",0,100),
        ("HR-002","Code of Conduct",0,100),
        ("IT-001","Information Security Awareness",0,100),
        ("MFG-001","Lean Manufacturing Basics",70,95),
        ("MFG-002","5S Workplace Organization",70,95),
        ("QA-001","Quality Management System",65,100),
        ("ENG-001","CAD Software Proficiency",75,100),
        ("FIN-001","Financial Compliance",75,100),
    ]
    rows = []
    active_emps = [e for e in employees if e["status"] == "Active"]
    for emp in active_emps:
        num_courses = random.randint(2, len(courses))
        sampled = random.sample(courses, num_courses)
        for cid, cname, score_lo, score_hi in sampled:
            yr = random.randint(2024, 2026)
            mo = random.randint(1, 6) if yr == 2026 else random.randint(1, 12)
            dy = random.randint(1, 28)
            rows.append({
                "emp_id": emp["emp_id"], "course_id": cid, "course_name": cname,
                "completion_date": fmt(date(yr, mo, dy)),
                "score": random.randint(score_lo, score_hi),
            })
    write_csv(DATA / "hr/training_completions.csv",
              ["emp_id","course_id","course_name","completion_date","score"], rows)

# ── Finance ───────────────────────────────────────────────────────────────────

GL_ACCOUNTS = [
    ("5000","Revenue"),
    ("6000","Cost of Goods Sold"),
    ("6100","Direct Materials"),
    ("6200","Direct Labor"),
    ("6300","Manufacturing Overhead"),
    ("7000","Salaries & Benefits"),
    ("7100","Travel & Entertainment"),
    ("7200","Professional Services"),
    ("7300","Facilities"),
    ("7400","Depreciation"),
    ("7500","IT & Software"),
    ("7600","Marketing"),
    ("8000","Research & Development"),
    ("9000","Capital Expenditure"),
]

DEPT_BUDGET_SHARE = {
    "Engineering": 0.12, "Finance": 0.04, "HR": 0.03, "IT": 0.05,
    "Manufacturing": 0.48, "Procurement": 0.03, "Quality": 0.06,
    "Sales": 0.10, "EHS": 0.02, "Executive": 0.07,
}

TOTAL_ANNUAL_BUDGET = 42_000_000  # ~$42M annual

def gen_gl_summary_monthly():
    months = months_between(date(2023, 1, 1), date(2026, 7, 1))
    rows = []
    for dept in DEPTS:
        dept_share = DEPT_BUDGET_SHARE[dept]
        for acct_id, acct_name in GL_ACCOUNTS:
            # Not all depts use all accounts
            if acct_id in ("5000",) and dept != "Sales":
                continue
            if acct_id in ("8000",) and dept not in ("Engineering","Manufacturing"):
                continue
            if acct_id in ("9000",):
                continue  # handled in capex
            acct_share = {"6100":0.25,"6200":0.18,"6300":0.10,"7000":0.20,"7100":0.03,
                          "7200":0.05,"7300":0.06,"7400":0.04,"7500":0.03,"7600":0.03,
                          "8000":0.03,"5000":1.0,"6000":0.60}.get(acct_id, 0.04)
            monthly_budget = TOTAL_ANNUAL_BUDGET * dept_share * acct_share / 12

            for m in months:
                budget = round(monthly_budget * jitter(1, 0.03))
                # Material cost variance: 6100 runs 8-12% over budget starting Feb 2026
                if acct_id == "6100" and m >= date(2026, 2, 1):
                    overrun_pct = random.uniform(0.08, 0.12)
                    actual = round(budget * (1 + overrun_pct))
                else:
                    # Normal variance ±5%
                    actual = round(budget * jitter(1, 0.05))
                variance = actual - budget
                rows.append({
                    "month": fmt(m), "dept": dept, "account_id": acct_id,
                    "account_name": acct_name, "budget": budget,
                    "actual": actual, "variance": variance,
                })
    write_csv(DATA / "finance/gl_summary_monthly.csv",
              ["month","dept","account_id","account_name","budget","actual","variance"], rows)

def gen_budget_2026():
    rows = []
    quarters = ["Q1_budget","Q2_budget","Q3_budget","Q4_budget"]
    for dept in DEPTS:
        dept_share = DEPT_BUDGET_SHARE[dept]
        for acct_id, acct_name in GL_ACCOUNTS:
            if acct_id == "5000" and dept != "Sales":
                continue
            acct_share = {"6100":0.25,"6200":0.18,"6300":0.10,"7000":0.20,"7100":0.03,
                          "7200":0.05,"7300":0.06,"7400":0.04,"7500":0.03,"7600":0.03,
                          "8000":0.03,"5000":1.0,"6000":0.60,"9000":0.05}.get(acct_id, 0.04)
            annual = TOTAL_ANNUAL_BUDGET * dept_share * acct_share
            row = {"dept": dept, "account_id": acct_id, "account_name": acct_name}
            for q in quarters:
                row[q] = round(annual / 4 * jitter(1, 0.02))
            rows.append(row)
    write_csv(DATA / "finance/budget_2026.csv",
              ["dept","account_id","account_name"] + quarters, rows)

def gen_actuals_2026():
    months = months_between(date(2026, 1, 1), date(2026, 6, 1))
    rows = []
    for dept in DEPTS:
        dept_share = DEPT_BUDGET_SHARE[dept]
        for acct_id, acct_name in GL_ACCOUNTS:
            if acct_id == "5000" and dept != "Sales":
                continue
            acct_share = {"6100":0.25,"6200":0.18,"6300":0.10,"7000":0.20,"7100":0.03,
                          "7200":0.05,"7300":0.06,"7400":0.04,"7500":0.03,"7600":0.03,
                          "8000":0.03,"5000":1.0,"6000":0.60,"9000":0.05}.get(acct_id, 0.04)
            monthly_budget = TOTAL_ANNUAL_BUDGET * dept_share * acct_share / 12
            for m in months:
                if acct_id == "6100" and m >= date(2026, 2, 1):
                    actual = round(monthly_budget * (1 + random.uniform(0.08, 0.12)))
                else:
                    actual = round(monthly_budget * jitter(1, 0.05))
                rows.append({
                    "dept": dept, "account_id": acct_id, "account_name": acct_name,
                    "month": fmt(m), "actual": actual,
                })
    write_csv(DATA / "finance/actuals_2026.csv",
              ["dept","account_id","account_name","month","actual"], rows)

def gen_forecast_2026():
    rows = []
    for dept in DEPTS:
        dept_share = DEPT_BUDGET_SHARE[dept]
        for acct_id, acct_name in GL_ACCOUNTS:
            if acct_id == "5000" and dept != "Sales":
                continue
            acct_share = {"6100":0.25,"6200":0.18,"6300":0.10,"7000":0.20,"7100":0.03,
                          "7200":0.05,"7300":0.06,"7400":0.04,"7500":0.03,"7600":0.03,
                          "8000":0.03,"5000":1.0,"6000":0.60,"9000":0.05}.get(acct_id, 0.04)
            annual_budget = TOTAL_ANNUAL_BUDGET * dept_share * acct_share
            if acct_id == "6100":
                full_year_forecast = round(annual_budget * 1.09)
                over_budget_flag = "Y"
            else:
                full_year_forecast = round(annual_budget * jitter(1, 0.04))
                over_budget_flag = "Y" if full_year_forecast > annual_budget * 1.03 else "N"
            rows.append({
                "dept": dept, "account_id": acct_id, "account_name": acct_name,
                "annual_budget": round(annual_budget),
                "full_year_forecast": full_year_forecast,
                "variance": full_year_forecast - round(annual_budget),
                "over_budget_flag": over_budget_flag,
            })
    write_csv(DATA / "finance/forecast_2026.csv",
              ["dept","account_id","account_name","annual_budget","full_year_forecast","variance","over_budget_flag"], rows)

def gen_capex_projects():
    projects = [
        ("CAP-001","CNC Machine Upgrade - Plant A","Manufacturing",850000),
        ("CAP-002","ERP System Modernization","IT",1200000),
        ("CAP-003","Roof Replacement - Plant B","Facilities",380000),
        ("CAP-004","Precision Measurement Lab","Quality",420000),
        ("CAP-005","Conveyor System Replacement","Manufacturing",290000),
        ("CAP-006","HVAC Upgrade - HQ","Facilities",175000),
        ("CAP-007","Solar Panel Installation - Plant A","EHS",650000),
        ("CAP-008","Warehouse Management System","Procurement",310000),
    ]
    statuses = ["In Progress","Completed","On Hold","Planning"]
    rows = []
    for pid, name, dept, budget in projects:
        pct = random.uniform(0.2, 0.95)
        spent = round(budget * pct)
        status = random.choice(statuses)
        rows.append({
            "project_id": pid, "name": name, "dept": dept,
            "approved_budget": budget, "spent_to_date": spent,
            "pct_spent": round(pct * 100, 1), "status": status,
        })
    write_csv(DATA / "finance/capex_projects.csv",
              ["project_id","name","dept","approved_budget","spent_to_date","pct_spent","status"], rows)

# ── Sales ─────────────────────────────────────────────────────────────────────

CUSTOMER_NAMES = [
    "Apex Aerospace LLC","Bolt Dynamics Inc","Cascade Defense Systems","Delta Precision Works",
    "Eagle Components Corp","Fortis Automotive","Greenfield Industries","Harbor Medical Devices",
    "Ironclad Manufacturing","Juniper Industrial","Keystone Fabricators","Lighthouse Defense",
    "Meridian Automotive Parts","Northstar Aerospace","Orion Systems Group","Pinnacle Tools",
    "Quantum Precision Inc","Redwood Industrial","Sierra Aerospace","Titan Defense Solutions",
    "Universal Components","Vantage Medical","Westfield Manufacturing","Xcel Automotive",
    "Yellowstone Industrial","Zenith Precision","Atlas Defense Corp","Bravo Components",
    "Centurion Aerospace","Diamond Industrial","Ember Medical","Falcon Automotive",
    "Galaxy Manufacturing","Helix Defense","Indus Precision","Journey Components",
    "Kinetic Industrial","Liberty Medical","Maverick Aerospace","Nova Automotive",
    "Omega Defense","Pioneer Industrial","Quartz Precision","Ranger Components",
    "Stellar Medical","Triumph Automotive","Union Aerospace","Viking Defense",
    "Warp Industrial","Zephyr Components",
]

def gen_customers():
    tiers = ["Platinum","Gold","Silver","Bronze"]
    industries = ["Aerospace","Automotive","Defense","Medical","Industrial"]
    regions = ["Midwest","Northeast","Southeast","West","Southwest"]
    rows = []
    for i, cid in enumerate(CUSTOMER_IDS):
        name = CUSTOMER_NAMES[i % len(CUSTOMER_NAMES)]
        rows.append({
            "customer_id": cid, "name": name,
            "industry": industries[i % len(industries)],
            "region": regions[i % len(regions)],
            "tier": tiers[min(i // 13, 3)],
            "ytd_revenue": round(random.uniform(50000, 2500000), -2),
        })
    write_csv(DATA / "sales/customers.csv",
              ["customer_id","name","industry","region","tier","ytd_revenue"], rows)
    return rows

def gen_orders():
    rows = []
    oid = 10001
    current = date(2023, 1, 1)
    end = date(2026, 6, 30)
    while current <= end:
        n_orders = random.randint(8, 22)
        for _ in range(n_orders):
            cid = random.choice(CUSTOMER_IDS)
            pid = random.choice(PRODUCT_IDS)
            order_date = current + timedelta(days=random.randint(0, 6))
            ship_date = order_date + timedelta(days=random.randint(14, 45))
            qty = random.randint(10, 500)
            unit_price = round(random.uniform(25, 850), 2)
            # Q2 2026 slippage: revenue 15% below normal
            if date(2026, 4, 1) <= order_date <= date(2026, 6, 30):
                unit_price *= 0.85
                qty = int(qty * 0.85)
            revenue = round(qty * unit_price, 2)
            rows.append({
                "order_id": f"ORD{oid}", "customer_id": cid, "product_id": pid,
                "order_date": fmt(order_date), "ship_date": fmt(ship_date),
                "qty": qty, "unit_price": unit_price, "revenue": revenue,
            })
            oid += 1
        current += timedelta(weeks=1)
    write_csv(DATA / "sales/orders.csv",
              ["order_id","customer_id","product_id","order_date","ship_date","qty","unit_price","revenue"], rows)

def gen_sales_forecast_monthly():
    months = months_between(date(2025, 1, 1), date(2026, 12, 1))
    rows = []
    for pl in PRODUCT_LINES:
        base_forecast = random.uniform(1_200_000, 3_500_000)
        for m in months:
            seasonal = 1 + 0.1 * (m.month in [3, 4, 9, 10]) - 0.05 * (m.month in [1, 7])
            forecast = round(base_forecast * seasonal / 12)
            # Q2 2026 slippage
            if date(2026, 4, 1) <= m <= date(2026, 6, 1):
                actual = round(forecast * random.uniform(0.82, 0.88))
            elif m <= date(2026, 6, 1):
                actual = round(forecast * jitter(1, 0.06))
            else:
                actual = None
            variance = (actual - forecast) if actual is not None else None
            rows.append({
                "month": fmt(m), "product_line": pl,
                "forecast": forecast, "actual": actual if actual else "",
                "variance": variance if variance is not None else "",
            })
    write_csv(DATA / "sales/sales_forecast_monthly.csv",
              ["month","product_line","forecast","actual","variance"], rows)

def gen_pipeline():
    stages = ["Prospecting","Qualification","Proposal","Negotiation","Closed Won","Closed Lost"]
    rows = []
    for i in range(1, 121):
        cid = random.choice(CUSTOMER_IDS)
        stage = random.choice(stages)
        value = round(random.uniform(25000, 1500000), -2)
        prob = {"Prospecting":10,"Qualification":25,"Proposal":50,"Negotiation":75,
                "Closed Won":100,"Closed Lost":0}[stage]
        close_date = date(2026, random.randint(7, 12), random.randint(1, 28))
        rows.append({
            "opportunity_id": f"OPP{i:04d}", "customer_id": cid,
            "stage": stage, "value": value, "probability_pct": prob,
            "expected_close": fmt(close_date),
            "weighted_value": round(value * prob / 100, -2),
        })
    write_csv(DATA / "sales/pipeline.csv",
              ["opportunity_id","customer_id","stage","value","probability_pct","expected_close","weighted_value"], rows)

# ── Manufacturing ─────────────────────────────────────────────────────────────

def gen_production_weekly():
    weeks = weeks_ending(date(2023, 1, 1), date(2026, 6, 29))
    rows = []
    for w in weeks:
        for line in LINE_IDS:
            pid = random.choice(PRODUCT_IDS[:8])
            planned = random.randint(400, 900)
            eff = random.uniform(0.88, 0.97)
            actual = int(planned * eff)

            # Line 2 scrap rate climbs from 2.1% to 4.8% Mar-Jun 2026
            if line == "L2" and w >= date(2026, 3, 1):
                weeks_since = (w - date(2026, 3, 1)).days / 7
                scrap_rate = 0.021 + (0.048 - 0.021) * min(weeks_since / 17, 1)
                scrap_rate *= jitter(1, 0.1)
            else:
                scrap_rate = random.uniform(0.015, 0.025)

            scrap = int(actual * scrap_rate)
            downtime = round(random.uniform(0.5, 6.0), 1) if random.random() < 0.6 else 0
            rows.append({
                "week_ending": fmt(w), "line_id": line, "product_id": pid,
                "planned_units": planned, "actual_units": actual,
                "scrap_units": scrap, "scrap_rate_pct": round(scrap_rate * 100, 2),
                "downtime_hours": downtime,
            })
    write_csv(DATA / "manufacturing/production_weekly.csv",
              ["week_ending","line_id","product_id","planned_units","actual_units",
               "scrap_units","scrap_rate_pct","downtime_hours"], rows)

def gen_production_monthly():
    months = months_between(date(2023, 1, 1), date(2026, 7, 1))
    rows = []
    for m in months:
        for pid in PRODUCT_IDS[:10]:
            planned = random.randint(1500, 4000)
            eff = random.uniform(0.87, 0.96)
            actual = int(planned * eff)
            rows.append({
                "month": fmt(m), "product_id": pid,
                "planned_units": planned, "actual_units": actual,
                "efficiency_pct": round(eff * 100, 1),
            })
    write_csv(DATA / "manufacturing/production_monthly.csv",
              ["month","product_id","planned_units","actual_units","efficiency_pct"], rows)

def gen_oee_weekly():
    weeks = weeks_ending(date(2023, 1, 1), date(2026, 6, 29))
    rows = []
    for w in weeks:
        for line in LINE_IDS:
            avail = round(random.uniform(0.88, 0.97), 3)
            perf = round(random.uniform(0.85, 0.96), 3)
            # Line 2 quality drops as scrap increases
            if line == "L2" and w >= date(2026, 3, 1):
                weeks_since = (w - date(2026, 3, 1)).days / 7
                qual = round(max(0.92, 0.975 - 0.027 * min(weeks_since / 17, 1) * jitter(1, 0.05)), 3)
            else:
                qual = round(random.uniform(0.96, 0.985), 3)
            oee = round(avail * perf * qual, 3)
            rows.append({
                "week_ending": fmt(w), "line_id": line,
                "availability": avail, "performance": perf,
                "quality": qual, "oee": oee,
            })
    write_csv(DATA / "manufacturing/oee_weekly.csv",
              ["week_ending","line_id","availability","performance","quality","oee"], rows)

def gen_inventory_monthly():
    months = months_between(date(2023, 1, 1), date(2026, 7, 1))
    categories = ["Raw Material","WIP","Finished Goods","MRO","Packaging"]
    rows = []
    for m in months:
        for part_id in PART_IDS[:40]:
            cat = random.choice(categories)
            unit_cost = round(random.uniform(2.5, 485.0), 2)
            qty_on_hand = random.randint(50, 5000)
            qty_on_order = random.randint(0, 2000)
            rows.append({
                "month": fmt(m), "part_id": part_id, "category": cat,
                "qty_on_hand": qty_on_hand, "qty_on_order": qty_on_order,
                "unit_cost": unit_cost, "total_value": round(qty_on_hand * unit_cost, 2),
            })
    write_csv(DATA / "manufacturing/inventory_monthly.csv",
              ["month","part_id","category","qty_on_hand","qty_on_order","unit_cost","total_value"], rows)

def gen_work_orders():
    statuses = ["Open","In Progress","Completed","On Hold","Cancelled"]
    rows = []
    for i in range(1, 501):
        pid = random.choice(PRODUCT_IDS)
        line = random.choice(LINE_IDS)
        start = date(2025, 1, 1) + timedelta(days=random.randint(0, 550))
        duration = random.randint(1, 21)
        end = start + timedelta(days=duration)
        planned_hrs = round(random.uniform(4, 80), 1)
        actual_hrs = round(planned_hrs * random.uniform(0.8, 1.3), 1)
        status = "Completed" if end <= date(2026, 6, 30) else random.choice(statuses[:3])
        rows.append({
            "wo_id": f"WO{i:05d}", "product_id": pid, "line_id": line,
            "start_date": fmt(start), "end_date": fmt(end), "status": status,
            "planned_hrs": planned_hrs, "actual_hrs": actual_hrs,
        })
    write_csv(DATA / "manufacturing/work_orders.csv",
              ["wo_id","product_id","line_id","start_date","end_date","status","planned_hrs","actual_hrs"], rows)

# ── Engineering ───────────────────────────────────────────────────────────────

ENG_LEAD_NAMES = ["Dana Kovacs","Marcus Ellsworth","Priya Nair","Chen Wei","Samantha Torres",
                  "Darnell Washington","Ingrid Halvorsen","Tobias Brennan"]

ENG_PROJECTS = [
    ("EPRJ-001","Next-Gen Aerospace Bracket","New Product",date(2025,1,15),date(2026,3,31),380000),
    ("EPRJ-002","Automotive Seal Redesign","Redesign",date(2025,3,1),date(2025,12,31),175000),
    ("EPRJ-003","Line 2 Process Optimization","Process Improvement",date(2025,6,1),date(2026,6,30),220000),
    ("EPRJ-004","Defense Connector Qualification","New Product",date(2025,9,1),date(2026,9,30),310000),
    ("EPRJ-005","Medical Implant Prototype","New Product",date(2026,1,1),date(2026,12,31),450000),
    ("EPRJ-006","ERP CAD Integration","IT/Engineering",date(2025,4,1),date(2025,10,31),95000),
    ("EPRJ-007","Titanium Alloy Study","R&D",date(2026,2,1),date(2026,8,31),180000),
    ("EPRJ-008","Customer Portal Integration","Sales Enablement",date(2025,11,1),date(2026,4,30),140000),
]

def gen_eng_projects():
    rows = []
    # Projects 003 and 007 get >20% cost overrun
    overrun_projs = {"EPRJ-003", "EPRJ-007"}
    for pid, name, ptype, start, planned_end, budget in ENG_PROJECTS:
        if pid in overrun_projs:
            spent_pct = random.uniform(0.88, 1.25)
            status = "Over Budget"
            actual_end = None
        else:
            spent_pct = random.uniform(0.40, 0.90)
            status = "On Track" if spent_pct < 0.85 else "At Risk"
            actual_end = planned_end if planned_end <= date(2026, 6, 30) and random.random() > 0.3 else None
        spent = round(budget * spent_pct, -2)
        rows.append({
            "project_id": pid, "name": name, "type": ptype,
            "start_date": fmt(start), "planned_end": fmt(planned_end),
            "actual_end": fmt(actual_end) if actual_end else "",
            "budget": budget, "spent": spent,
            "pct_spent": round(spent_pct * 100, 1),
            "status": status,
            "lead_engineer": random.choice(ENG_LEAD_NAMES),
        })
    write_csv(DATA / "engineering/projects.csv",
              ["project_id","name","type","start_date","planned_end","actual_end",
               "budget","spent","pct_spent","status","lead_engineer"], rows)

def gen_project_budget_monthly():
    months = months_between(date(2025, 1, 1), date(2026, 6, 1))
    overrun_projs = {"EPRJ-003", "EPRJ-007"}
    rows = []
    for pid, _, _, start, _, budget in ENG_PROJECTS:
        monthly_budget = round(budget / 18)
        for m in months:
            if m < date(start.year, start.month, 1):
                continue
            b = round(monthly_budget * jitter(1, 0.05))
            if pid in overrun_projs and m >= date(2026, 2, 1):
                actual = round(b * random.uniform(1.15, 1.30))
            else:
                actual = round(b * jitter(1, 0.08))
            rows.append({
                "project_id": pid, "month": fmt(m),
                "budget": b, "actual": actual, "variance": actual - b,
            })
    write_csv(DATA / "engineering/project_budget_monthly.csv",
              ["project_id","month","budget","actual","variance"], rows)

def gen_ecr_log():
    ecr_types = ["Design Change","Material Substitution","Process Change","Drawing Update","Supplier Change"]
    statuses = ["Open","Under Review","Approved","Rejected","Implemented"]
    rows = []
    for i in range(1, 121):
        proj = random.choice([p[0] for p in ENG_PROJECTS])
        d = date(2024, 1, 1) + timedelta(days=random.randint(0, 910))
        cost_impact = round(random.uniform(-5000, 45000), -2)
        rows.append({
            "ecr_id": f"ECR{i:04d}", "project_id": proj,
            "date": fmt(d), "type": random.choice(ecr_types),
            "description": f"ECR for {proj}: {random.choice(ecr_types).lower()} required",
            "status": random.choice(statuses),
            "cost_impact": cost_impact,
        })
    write_csv(DATA / "engineering/ecr_log.csv",
              ["ecr_id","project_id","date","type","description","status","cost_impact"], rows)

def gen_bom():
    rows = []
    for part_id in PART_IDS:
        prod_id = random.choice(PRODUCT_IDS[:10])
        unit_cost = round(random.uniform(1.5, 250.0), 2)
        rows.append({
            "part_id": part_id, "product_id": prod_id,
            "description": f"Component {part_id} for {prod_id}",
            "unit_cost": unit_cost, "qty_per_unit": random.randint(1, 12),
            "supplier_id": random.choice(SUPPLIER_IDS),
        })
    write_csv(DATA / "engineering/bom.csv",
              ["part_id","product_id","description","unit_cost","qty_per_unit","supplier_id"], rows)

# ── Quality ───────────────────────────────────────────────────────────────────

DEFECT_TYPES = ["Dimensional Out-of-Spec","Surface Finish","Material Defect",
                "Assembly Error","Contamination","Documentation Error","Other"]
DISPOSITIONS = ["Scrap","Rework","Use As-Is","Return to Supplier","Pending Review"]

def gen_ncr_log():
    rows = []
    for i in range(1, 301):
        d = date(2023, 1, 1) + timedelta(days=random.randint(0, 1280))
        line = random.choice(LINE_IDS)
        # Line 2 NCRs spike in 2026
        if line == "L2" and d >= date(2026, 3, 1) and random.random() < 0.4:
            qty = random.randint(15, 120)
        else:
            qty = random.randint(1, 40)
        cost = round(qty * random.uniform(25, 480), 2)
        rows.append({
            "ncr_id": f"NCR{i:04d}", "date": fmt(d),
            "line_id": line, "product_id": random.choice(PRODUCT_IDS),
            "defect_type": random.choice(DEFECT_TYPES),
            "qty_affected": qty, "disposition": random.choice(DISPOSITIONS),
            "cost_impact": cost,
        })
    write_csv(DATA / "quality/ncr_log.csv",
              ["ncr_id","date","line_id","product_id","defect_type","qty_affected","disposition","cost_impact"], rows)

def gen_audit_schedule():
    audit_types = ["Internal","External","Supplier","Process","System"]
    statuses = ["Scheduled","In Progress","Completed","Overdue"]
    rows = []
    for i in range(1, 61):
        d = date(2025, 1, 1) + timedelta(days=random.randint(0, 550))
        findings = random.randint(0, 12)
        rows.append({
            "audit_id": f"AUD{i:04d}", "date": fmt(d),
            "dept": random.choice(DEPTS), "type": random.choice(audit_types),
            "auditor": _gen_name(), "findings_count": findings,
            "status": random.choice(statuses),
        })
    write_csv(DATA / "quality/audit_schedule.csv",
              ["audit_id","date","dept","type","auditor","findings_count","status"], rows)

def gen_supplier_scorecard():
    rows = []
    quarters = [("2025-Q1",), ("2025-Q2",), ("2025-Q3",), ("2025-Q4",), ("2026-Q1",), ("2026-Q2",)]
    for sid in SUPPLIER_IDS[:15]:
        for (q,) in quarters:
            delivery = round(random.uniform(70, 99), 1)
            quality = round(random.uniform(72, 99), 1)
            price = round(random.uniform(65, 95), 1)
            overall = round((delivery * 0.35 + quality * 0.45 + price * 0.20), 1)
            rows.append({
                "supplier_id": sid, "quarter": q,
                "delivery_score": delivery, "quality_score": quality,
                "price_score": price, "overall_score": overall,
            })
    write_csv(DATA / "quality/supplier_scorecard.csv",
              ["supplier_id","quarter","delivery_score","quality_score","price_score","overall_score"], rows)

def gen_inspection_results():
    rows = []
    for i in range(1, 601):
        d = date(2023, 1, 1) + timedelta(days=random.randint(0, 1280))
        part = random.choice(PART_IDS[:40])
        qty_insp = random.randint(20, 500)
        fail_rate = random.uniform(0.005, 0.04)
        qty_failed = int(qty_insp * fail_rate)
        qty_passed = qty_insp - qty_failed
        rows.append({
            "inspection_id": f"INSP{i:05d}", "date": fmt(d),
            "part_id": part, "qty_inspected": qty_insp,
            "qty_passed": qty_passed, "qty_failed": qty_failed,
            "disposition": random.choice(DISPOSITIONS),
        })
    write_csv(DATA / "quality/inspection_results.csv",
              ["inspection_id","date","part_id","qty_inspected","qty_passed","qty_failed","disposition"], rows)

# ── Procurement ───────────────────────────────────────────────────────────────

SUPPLIER_NAMES = [
    "Acme Metal Supply","Brightline Components","Cascade Alloys","Delta Fasteners",
    "Eagle Plastics","Fortis Chemical","Greenfield Bearings","Harbor Steel",
    "Ironside Materials","Juniper Coatings","Keystone Tooling","Lighthouse Polymers",
    "Meridian Lubricants","Northstar Castings","Orion Forgings","Pinnacle Wire",
    "Quantum Adhesives","Redwood Gaskets","Sierra Springs","Titan Seals",
    "Universal Bearings","Vantage Abrasives","Westfield Tubes","Xcel Composites","Yellowstone Valves",
]

PO_STATUSES = ["Open","Received","Partial","Cancelled","Invoiced"]

def gen_purchase_orders():
    rows = []
    for i in range(1, 701):
        sid = random.choice(SUPPLIER_IDS)
        d = date(2024, 1, 1) + timedelta(days=random.randint(0, 910))
        due = d + timedelta(days=random.randint(7, 60))
        lines = random.randint(1, 12)
        total = round(random.uniform(500, 85000), 2)
        rows.append({
            "po_id": f"PO{i:05d}", "supplier_id": sid,
            "date": fmt(d), "due_date": fmt(due),
            "line_items_count": lines, "total_value": total,
            "status": random.choice(PO_STATUSES),
        })
    write_csv(DATA / "procurement/purchase_orders.csv",
              ["po_id","supplier_id","date","due_date","line_items_count","total_value","status"], rows)

def gen_supplier_master():
    categories = ["Raw Materials","Fasteners","Tooling","MRO","Chemicals","Packaging","Services"]
    payment_terms = ["Net 30","Net 45","Net 60","2/10 Net 30"]
    rows = []
    for i, sid in enumerate(SUPPLIER_IDS):
        rows.append({
            "supplier_id": sid, "name": SUPPLIER_NAMES[i % len(SUPPLIER_NAMES)],
            "category": random.choice(categories),
            "lead_time_days": random.randint(3, 60),
            "payment_terms": random.choice(payment_terms),
            "preferred": "Y" if random.random() > 0.4 else "N",
        })
    write_csv(DATA / "procurement/supplier_master.csv",
              ["supplier_id","name","category","lead_time_days","payment_terms","preferred"], rows)

def gen_spend_by_category_monthly():
    months = months_between(date(2023, 1, 1), date(2026, 7, 1))
    categories = ["Raw Materials","Fasteners","Tooling","MRO","Chemicals","Packaging","Services"]
    base_spends = {"Raw Materials":850000,"Fasteners":120000,"Tooling":95000,
                   "MRO":65000,"Chemicals":45000,"Packaging":35000,"Services":80000}
    rows = []
    for m in months:
        for cat in categories:
            budget = round(base_spends[cat] / 12 * jitter(1, 0.03))
            # Raw materials over budget from Feb 2026
            if cat == "Raw Materials" and m >= date(2026, 2, 1):
                actual = round(budget * random.uniform(1.08, 1.12))
            else:
                actual = round(budget * jitter(1, 0.07))
            rows.append({
                "month": fmt(m), "category": cat,
                "budget": budget, "actual": actual, "variance": actual - budget,
            })
    write_csv(DATA / "procurement/spend_by_category_monthly.csv",
              ["month","category","budget","actual","variance"], rows)

# ── IT ────────────────────────────────────────────────────────────────────────

ASSET_TYPES = ["Laptop","Desktop","Monitor","Server","Network Switch","Printer","Tablet","Phone","UPS"]
MAKES = ["Dell","HP","Lenovo","Apple","Cisco","Brother","Samsung","Polycom"]

def gen_it_assets(employees):
    rows = []
    active_emps = [e for e in employees if e["status"] == "Active"]
    for i, emp in enumerate(active_emps):
        # Each employee gets a laptop
        purchase_d = date(2020, 1, 1) + timedelta(days=random.randint(0, 2000))
        warranty_end = purchase_d + timedelta(days=3*365)
        rows.append({
            "asset_id": f"AST{i+1:05d}", "type": "Laptop",
            "make_model": f"{random.choice(MAKES[:4])} {random.choice(['ProBook','ThinkPad','XPS','MacBook Pro'])}",
            "dept": emp["dept"], "assigned_to": emp["emp_id"],
            "purchase_date": fmt(purchase_d), "warranty_end": fmt(warranty_end),
            "status": "Active",
        })
    # Add server/network assets
    for i in range(40):
        purchase_d = date(2019, 1, 1) + timedelta(days=random.randint(0, 2500))
        warranty_end = purchase_d + timedelta(days=5*365)
        rows.append({
            "asset_id": f"AST{len(active_emps)+i+1:05d}",
            "type": random.choice(["Server","Network Switch","UPS","Printer"]),
            "make_model": f"{random.choice(MAKES)} Enterprise",
            "dept": random.choice(DEPTS), "assigned_to": "IT",
            "purchase_date": fmt(purchase_d), "warranty_end": fmt(warranty_end),
            "status": random.choice(["Active","End of Life","Maintenance"]),
        })
    write_csv(DATA / "it/assets.csv",
              ["asset_id","type","make_model","dept","assigned_to","purchase_date","warranty_end","status"], rows)

def gen_it_tickets():
    categories = ["Hardware","Software","Network","Access","Email","Printing","Security","Other"]
    priorities = ["Critical","High","Medium","Low"]
    rows = []
    for i in range(1, 1201):
        d = date(2024, 1, 1) + timedelta(days=random.randint(0, 910))
        priority = random.choices(priorities, weights=[5,15,50,30])[0]
        res_hrs = {"Critical": random.uniform(0.5, 4), "High": random.uniform(2, 24),
                   "Medium": random.uniform(8, 72), "Low": random.uniform(24, 168)}[priority]
        resolved_d = d + timedelta(hours=res_hrs)
        rows.append({
            "ticket_id": f"TKT{i:05d}", "date": fmt(d),
            "category": random.choice(categories), "priority": priority,
            "dept": random.choice(DEPTS),
            "description": f"{random.choice(categories)} issue reported",
            "resolved_date": fmt(resolved_d),
            "resolution_hrs": round(res_hrs, 1),
        })
    write_csv(DATA / "it/tickets.csv",
              ["ticket_id","date","category","priority","dept","description","resolved_date","resolution_hrs"], rows)

def gen_software_licenses():
    products = [
        ("SolidWorks","Dassault Systèmes",45,38,date(2026,12,31),28500),
        ("Microsoft 365","Microsoft",320,298,date(2027,1,31),64000),
        ("AutoCAD","Autodesk",20,17,date(2026,9,30),18000),
        ("SAP ERP","SAP",50,48,date(2027,6,30),125000),
        ("Salesforce","Salesforce",35,31,date(2026,11,30),52500),
        ("Adobe Creative","Adobe",12,9,date(2026,10,31),8400),
        ("MATLAB","MathWorks",10,8,date(2027,3,31),22000),
        ("Zoom","Zoom Video",320,310,date(2027,1,31),38400),
        ("Slack","Salesforce",320,285,date(2027,1,31),28800),
        ("Jira","Atlassian",80,72,date(2026,8,31),9600),
        ("Confluence","Atlassian",80,65,date(2026,8,31),6400),
        ("Tableau","Salesforce",25,18,date(2026,12,31),35000),
        ("GitHub Enterprise","GitHub",60,55,date(2027,1,31),21000),
        ("CrowdStrike","CrowdStrike",320,320,date(2026,12,31),48000),
        ("DocuSign","DocuSign",30,22,date(2026,9,30),9000),
    ]
    rows = []
    for i, (prod, vendor, seats_p, seats_u, renewal, cost) in enumerate(products):
        rows.append({
            "license_id": f"LIC{i+1:03d}", "product": prod, "vendor": vendor,
            "seats_purchased": seats_p, "seats_used": seats_u,
            "utilization_pct": round(seats_u/seats_p*100, 1),
            "renewal_date": fmt(renewal), "annual_cost": cost,
        })
    write_csv(DATA / "it/software_licenses.csv",
              ["license_id","product","vendor","seats_purchased","seats_used",
               "utilization_pct","renewal_date","annual_cost"], rows)

# ── EHS ───────────────────────────────────────────────────────────────────────

INCIDENT_TYPES = ["Near Miss","First Aid","Recordable Injury","Lost Time Injury",
                  "Property Damage","Environmental","Security"]
SEVERITIES = ["Low","Medium","High","Critical"]

def gen_ehs_incidents():
    rows = []
    for i in range(1, 121):
        d = date(2023, 1, 1) + timedelta(days=random.randint(0, 1280))
        itype = random.choices(INCIDENT_TYPES, weights=[30,25,20,10,8,5,2])[0]
        severity = random.choices(SEVERITIES, weights=[40,35,20,5])[0]
        recordable = "Y" if itype in ("Recordable Injury","Lost Time Injury") else "N"
        days_lost = random.randint(1, 30) if itype == "Lost Time Injury" else 0
        rows.append({
            "incident_id": f"INC{i:04d}", "date": fmt(d),
            "type": itype, "dept": random.choice(DEPTS),
            "severity": severity, "recordable": recordable,
            "days_lost": days_lost,
            "corrective_action": f"CA issued {fmt(d + timedelta(days=random.randint(1,7)))}",
        })
    write_csv(DATA / "ehs/incidents.csv",
              ["incident_id","date","type","dept","severity","recordable","days_lost","corrective_action"], rows)

def gen_ehs_training_compliance():
    training_types = ["OSHA 10-Hour","OSHA 30-Hour","Forklift","Hazmat","Fire Safety",
                      "PPE","Lockout Tagout","Confined Space","First Aid/CPR","Emergency Response"]
    rows = []
    for dept in DEPTS:
        hc = DEPT_HEADCOUNT[dept]
        for tt in training_types:
            required = hc if tt in ("Fire Safety","PPE","Emergency Response") else max(2, int(hc * 0.6))
            completed = random.randint(int(required * 0.75), required)
            pct = round(completed / required * 100, 1)
            due = date(2026, random.randint(6, 12), 30)
            rows.append({
                "dept": dept, "training_type": tt, "required_count": required,
                "completed_count": completed, "pct_complete": pct, "due_date": fmt(due),
            })
    write_csv(DATA / "ehs/training_compliance.csv",
              ["dept","training_type","required_count","completed_count","pct_complete","due_date"], rows)

def gen_ehs_inspections():
    areas = ["Plant A Floor","Plant B Floor","HQ Office","Warehouse","Loading Dock",
             "Chemical Storage","Electrical Room","Roof Access","Parking Lot","Lab"]
    statuses = ["Open","Closed","In Progress"]
    rows = []
    for i in range(1, 151):
        d = date(2024, 1, 1) + timedelta(days=random.randint(0, 910))
        findings = random.randint(0, 15)
        critical = random.randint(0, min(findings, 3))
        rows.append({
            "inspection_id": f"EHSI{i:04d}", "date": fmt(d),
            "area": random.choice(areas), "inspector": _gen_name(),
            "findings_count": findings, "critical_findings": critical,
            "status": random.choice(statuses),
        })
    write_csv(DATA / "ehs/inspections.csv",
              ["inspection_id","date","area","inspector","findings_count","critical_findings","status"], rows)

# ── Executive ─────────────────────────────────────────────────────────────────

KPIS = [
    ("Revenue","Financial","$M"),
    ("Gross Margin %","Financial","%"),
    ("EBITDA %","Financial","%"),
    ("OEE","Manufacturing","%"),
    ("Scrap Rate","Manufacturing","%"),
    ("On-Time Delivery","Manufacturing","%"),
    ("Headcount","HR","count"),
    ("Voluntary Turnover Rate","HR","%"),
    ("Open Positions","HR","count"),
    ("NPS","Sales","score"),
    ("Bookings","Sales","$M"),
    ("Pipeline Coverage","Sales","ratio"),
    ("First Pass Yield","Quality","%"),
    ("Customer PPM","Quality","ppm"),
    ("OSHA Recordable Rate","EHS","rate"),
    ("Days Since Last Recordable","EHS","days"),
    ("IT Ticket Avg Resolution","IT","hrs"),
    ("Capex Spend vs Plan","Finance","%"),
]

KPI_TARGETS = {
    "Revenue": 3.8, "Gross Margin %": 38.0, "EBITDA %": 14.0,
    "OEE": 82.0, "Scrap Rate": 2.5, "On-Time Delivery": 95.0,
    "Headcount": 320, "Voluntary Turnover Rate": 8.0, "Open Positions": 12,
    "NPS": 52, "Bookings": 4.2, "Pipeline Coverage": 3.0,
    "First Pass Yield": 97.0, "Customer PPM": 250, "OSHA Recordable Rate": 1.5,
    "Days Since Last Recordable": 90, "IT Ticket Avg Resolution": 18.0,
    "Capex Spend vs Plan": 95.0,
}

def gen_kpi_monthly():
    months = months_between(date(2023, 1, 1), date(2026, 7, 1))
    rows = []
    for m in months:
        for kpi_name, category, unit in KPIS:
            target = KPI_TARGETS[kpi_name]
            # Pattern overrides
            if kpi_name == "Scrap Rate" and m >= date(2026, 3, 1):
                actual = round(target * random.uniform(1.4, 1.9), 2)
                status = "Red"
            elif kpi_name == "Bookings" and date(2026, 4, 1) <= m <= date(2026, 6, 1):
                actual = round(target * random.uniform(0.82, 0.88), 2)
                status = "Red"
            elif kpi_name == "Voluntary Turnover Rate" and (date(2026, 1, 1) <= m <= date(2026, 3, 1) or m == date(2026, 6, 1)):
                actual = round(target * random.uniform(1.5, 2.2), 2)
                status = "Red"
            elif kpi_name in ("Revenue","Gross Margin %","OEE","On-Time Delivery","First Pass Yield","NPS","Days Since Last Recordable"):
                actual = round(target * jitter(1, 0.05), 2)
                status = "Green" if actual >= target * 0.97 else "Yellow"
            else:
                actual = round(target * jitter(1, 0.08), 2)
                status = "Green" if actual >= target * 0.95 else ("Yellow" if actual >= target * 0.85 else "Red")
            rows.append({
                "month": fmt(m), "kpi_name": kpi_name, "category": category,
                "target": target, "actual": actual, "unit": unit, "status": status,
            })
    write_csv(DATA / "executive/kpi_monthly.csv",
              ["month","kpi_name","category","target","actual","unit","status"], rows)

def gen_risk_register():
    risks = [
        ("RSK-001","Supply Chain","Single-source dependency for titanium alloy",4,4,16,"VP Operations","Identify secondary supplier","Open"),
        ("RSK-002","Financial","Material cost inflation exceeding 10%",4,3,12,"CFO","Quarterly repricing clauses with top 5 suppliers","In Progress"),
        ("RSK-003","Operational","Line 2 scrap rate trend may require equipment rebuild",3,4,12,"VP Manufacturing","Root cause investigation underway","In Progress"),
        ("RSK-004","HR","Talent attrition in engineering; two key PMs at risk",4,3,12,"CHRO","Retention bonus program under review","Open"),
        ("RSK-005","Sales","Q2 forecast miss may indicate demand softening",3,4,12,"VP Sales","Accelerate pipeline development; add 2 reps","In Progress"),
        ("RSK-006","IT","ERP system end-of-support in 18 months",3,3,9,"CIO","Modernization project CAP-002 in progress","In Progress"),
        ("RSK-007","Regulatory","OSHA inspection scheduled Q3 2026",2,4,8,"EHS Director","Pre-audit self-inspection completed","Mitigated"),
        ("RSK-008","Customer","Top customer Apex Aerospace contract renewal due Aug 2026",3,5,15,"VP Sales","Contract negotiation initiated","Open"),
        ("RSK-009","Financial","Capex overrun risk on CNC upgrade project",2,3,6,"CFO","Weekly project reviews instituted","Mitigated"),
        ("RSK-010","Cybersecurity","Phishing attack surface post-remote-work expansion",3,4,12,"CIO","MFA deployed; awareness training Q2 2026","In Progress"),
    ]
    rows = []
    for risk_id, cat, desc, likelihood, impact, score, owner, mitigation, status in risks:
        rows.append({
            "risk_id": risk_id, "category": cat, "description": desc,
            "likelihood": likelihood, "impact": impact, "risk_score": score,
            "owner": owner, "mitigation": mitigation, "status": status,
        })
    write_csv(DATA / "executive/risk_register.csv",
              ["risk_id","category","description","likelihood","impact","risk_score","owner","mitigation","status"], rows)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Generating Simplicit Demo Company dataset...")
    print("\n[HR]")
    employees = gen_employees()
    gen_headcount_monthly(employees)
    gen_turnover_monthly(employees)
    gen_compensation_bands()
    gen_training_completions(employees)

    print("\n[Finance]")
    gen_gl_summary_monthly()
    gen_budget_2026()
    gen_actuals_2026()
    gen_forecast_2026()
    gen_capex_projects()

    print("\n[Sales]")
    gen_customers()
    gen_orders()
    gen_sales_forecast_monthly()
    gen_pipeline()

    print("\n[Manufacturing]")
    gen_production_weekly()
    gen_production_monthly()
    gen_oee_weekly()
    gen_inventory_monthly()
    gen_work_orders()

    print("\n[Engineering]")
    gen_eng_projects()
    gen_project_budget_monthly()
    gen_ecr_log()
    gen_bom()

    print("\n[Quality]")
    gen_ncr_log()
    gen_audit_schedule()
    gen_supplier_scorecard()
    gen_inspection_results()

    print("\n[Procurement]")
    gen_purchase_orders()
    gen_supplier_master()
    gen_spend_by_category_monthly()

    print("\n[IT]")
    gen_it_assets(employees)
    gen_it_tickets()
    gen_software_licenses()

    print("\n[EHS]")
    gen_ehs_incidents()
    gen_ehs_training_compliance()
    gen_ehs_inspections()

    print("\n[Executive]")
    gen_kpi_monthly()
    gen_risk_register()

    print("\nDone! All CSV files generated.")

if __name__ == "__main__":
    main()
