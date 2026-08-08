#!/usr/bin/env python3
"""Generate deterministic, non-sensitive fixtures for the SMB E2E repository."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
from pathlib import Path

import openpyxl


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_xlsx(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(fieldnames)
    for row in rows:
        ws.append([row.get(k) for k in fieldnames])
    wb.save(path)


def _write_json(path: Path, data: list | dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _generate_sales_fixtures(root: Path) -> list[dict]:
    customers = [
        {"customer_id": "CUST-1001", "name": "Acme Corp", "region": "West", "tier": "Enterprise"},
        {"customer_id": "CUST-1002", "name": "Globex", "region": "East", "tier": "Mid-Market"},
    ]
    _write_csv(root / "sales" / "customers.csv", customers, list(customers[0].keys()))

    orders = [
        {
            "order_id": f"ORD-{i:04d}",
            "customer_id": customers[i % 2]["customer_id"],
            "product": f"Widget-{i % 5}",
            "quantity": (i % 10) + 1,
            "unit_price": round(100 + i * 0.5, 2),
            "order_date": f"2026-0{(i % 9) + 1}-{(i % 28) + 1:02d}",
        }
        for i in range(100)
    ]
    _write_csv(root / "sales" / "sales_orders.csv", orders, list(orders[0].keys()))

    targets = [
        {"region": "West", "q1_target": 500000, "q2_target": 600000},
        {"region": "East", "q1_target": 450000, "q2_target": 550000},
    ]
    _write_xlsx(root / "sales" / "sales_targets.xlsx", targets, list(targets[0].keys()))
    return [
        {"relative_path": "sales/customers.csv", "expected_rows": 2, "expected_columns": 4},
        {"relative_path": "sales/sales_orders.csv", "expected_rows": 100, "expected_columns": 6},
        {"relative_path": "sales/sales_targets.xlsx", "expected_rows": 2, "expected_columns": 3},
    ]


def _generate_operations_fixtures(root: Path) -> list[dict]:
    work_orders = [
        {"work_order_id": f"WO-{i:04d}", "asset_id": f"AST-{1000 + i}", "priority": ("High", "Medium", "Low")[i % 3], "status": "Closed" if i % 2 else "Open"}
        for i in range(20)
    ]
    _write_json(root / "operations" / "work_orders.json", work_orders)

    equipment = [
        {"equipment_id": f"EQ-{i:03d}", "name": f"Pump {i}", "location": "Building A" if i % 2 else "Building B"}
        for i in range(10)
    ]
    xml = "<equipment>\n" + "\n".join(
        f"  <item id='{e['equipment_id']}'><name>{e['name']}</name><location>{e['location']}</location></item>"
        for e in equipment
    ) + "\n</equipment>"
    _write_text(root / "operations" / "equipment.xml", xml)
    return [
        {"relative_path": "operations/work_orders.json", "expected_rows": 20, "expected_columns": 4},
        {"relative_path": "operations/equipment.xml", "expected_rows": 10, "expected_columns": 3},
    ]


def _generate_document_fixtures(root: Path) -> list[dict]:
    # Placeholder documents.  The generator writes small files; the actual
    # binary formats are out of scope for a deterministic generator.
    docs: list[dict] = []
    for name, mime, text in [
        ("supplier_contract.pdf", "application/pdf", "Supplier contract placeholder."),
        ("quality_procedure.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "Quality procedure placeholder."),
        ("quarterly_review.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", "Quarterly review placeholder."),
        ("notes.txt", "text/plain", "These are test notes."),
    ]:
        path = root / "documents" / name
        _write_text(path, text)
        docs.append({"relative_path": f"documents/{name}", "mime_type": mime})
    return docs


def _generate_negative_fixtures(root: Path) -> list[dict]:
    # Empty file, corrupt xlsx bytes, disguised executable, EICAR test string.
    (root / "negative" / "empty.csv").write_text("")
    (root / "negative" / "corrupt.xlsx").write_bytes(b"PK\x03\x04notavalidexcel")
    (root / "negative" / "disguised_executable.csv").write_bytes(b"MZ" + b"\x00" * 100)
    (root / "negative" / "eicar-test-file.txt").write_text(
        "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    )

    # Oversized CSV is generated only if requested and is destroyed during teardown.
    oversized_path = root / "negative" / "oversized.csv"
    with oversized_path.open("w") as f:
        f.write("id\n")
        for i in range(1_000_000):
            f.write(f"{i}\n")

    (root / "outside-approved-root" / "must-not-import.csv").write_text("secret\n1\n")

    return [
        {"relative_path": "negative/empty.csv", "expected_destination": "rejected"},
        {"relative_path": "negative/corrupt.xlsx", "expected_destination": "rejected"},
        {"relative_path": "negative/disguised_executable.csv", "expected_destination": "rejected"},
        {"relative_path": "negative/eicar-test-file.txt", "expected_destination": "rejected"},
        {"relative_path": "negative/oversized.csv", "expected_destination": "rejected"},
        {"relative_path": "outside-approved-root/must-not-import.csv", "expected_destination": "rejected"},
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="fixtures", type=Path)
    parser.add_argument("--include-oversized", action="store_true")
    args = parser.parse_args()

    root = args.output / "tablescope-inbound"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    manifest: list[dict] = []
    manifest.extend(_generate_sales_fixtures(root))
    manifest.extend(_generate_operations_fixtures(root))
    manifest.extend(_generate_document_fixtures(root))
    manifest.extend(_generate_negative_fixtures(root))

    if not args.include_oversized:
        # Remove the oversized fixture unless explicitly requested.
        oversized = root / "negative" / "oversized.csv"
        if oversized.exists():
            oversized.unlink()
        manifest = [m for m in manifest if "oversized" not in m["relative_path"]]

    # Hash each generated file and add it to the manifest.
    for entry in manifest:
        path = root / entry["relative_path"]
        entry["sha256"] = _sha256(path)
        entry["size_bytes"] = path.stat().st_size

    manifest_path = args.output / "fixture-manifest.json"
    with manifest_path.open("w") as f:
        json.dump({
            "root": "tablescope-inbound",
            "files": manifest,
        }, f, indent=2)

    print(f"Generated {len(manifest)} fixtures at {root}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
