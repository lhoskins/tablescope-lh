#!/usr/bin/env python3
"""One-shot replace of 14 specific simplicit demo data sources.

Do NOT use scripts/install_demo_company.py --refresh-existing for this — that
regenerates all 81 CSVs from scratch with fresh random draws, which silently
changes every historical value (not just appends new ones). The 14 files
under docs/simplicit-refresh-2026-08-02/files/ are hand-extended: every
existing row is byte-identical to what's live; only trailing periods through
2026-08-01 (monthly) / 2026-07-27 (weekly) were appended, projected from each
series' own recent trend. This script replaces ONLY those 14 files via the
existing /replace endpoint, then reprocesses AI content the same way
--refresh-existing does.

Self-contained (stdlib only) so it can run regardless of which branch/commit
is checked out.

Usage:
    python scripts/refresh_simplicit_2026_08.py \\
        --api-url https://app.tablescope.cloud --email leonard.hoskins@gmail.com
"""
from __future__ import annotations

import argparse
import getpass
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

FILES_DIR = Path(__file__).resolve().parent.parent / "docs" / "simplicit-refresh-2026-08-02" / "files"

TARGET_FILES = [
    "sales_revenue_monthly.csv",
    "mfg_material_actuals_monthly.csv",
    "eng_labor_actuals_monthly.csv",
    "fin_gl_monthly.csv",
    "fin_budget_vs_actual_monthly.csv",
    "hr_headcount_plan.csv",
    "quality_defect_trends_monthly.csv",
    "procurement_material_price_history.csv",
    "it_system_availability_monthly.csv",
    "fin_indirect_rates_monthly.csv",
    "executive_kpi_scorecard_monthly.csv",
    "monthly_review_metrics.csv",
    "mfg_labor_actuals_weekly.csv",
    "mfg_scrap_weekly.csv",
]

_RESERVED = re.compile(r"[\\/:*?\"<>|$,]")
_MULTI_US = re.compile(r"_{2,}")
_TRIM_US = re.compile(r"^_+|_+$")


def compute_view_name(filename: str) -> str:
    """Mirror of platform-api's file_sources.compute_view_name()."""
    base, _, ext = filename.rpartition(".") if "." in filename else (filename, "", "")
    base = _RESERVED.sub("_", base).replace(" ", "_")
    base = _TRIM_US.sub("", _MULTI_US.sub("_", base)) or "file"
    return f"{base}_{ext.upper()}" if ext else base


class ApiError(RuntimeError):
    pass


class ApiClient:
    def __init__(self, base_url: str, *, token: str | None = None, insecure: bool = False) -> None:
        self.base = base_url.rstrip("/")
        self.token = token
        self._ctx = ssl._create_unverified_context() if insecure else None

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if extra:
            h.update(extra)
        return h

    def _request(self, method: str, path: str, *, data: bytes | None = None, headers: dict | None = None):
        url = path if path.startswith("http") else f"{self.base}{path}"
        req = urllib.request.Request(url, data=data, method=method, headers=self._headers(headers))
        try:
            with urllib.request.urlopen(req, timeout=180.0, context=self._ctx) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            raise ApiError(f"{method} {url} -> HTTP {e.code}: {body}") from None
        try:
            return json.loads(body) if body else None
        except json.JSONDecodeError:
            return {"raw": body}

    def post_json(self, path: str, payload: dict):
        return self._request("POST", path, data=json.dumps(payload).encode(),
                             headers={"Content-Type": "application/json"})

    def post_multipart(self, path: str, *, filename: str, file_bytes: bytes, content_type: str):
        boundary = f"----refresh{uuid.uuid4().hex}"
        body = bytearray()
        body += f"--{boundary}\r\n".encode()
        body += (f'Content-Disposition: form-data; name="file"; '
                 f'filename="{filename}"\r\n').encode()
        body += f"Content-Type: {content_type}\r\n\r\n".encode()
        body += file_bytes + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        return self._request("POST", path, data=bytes(body),
                             headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})

    def login(self, email: str, password: str) -> str:
        res = self.post_json("/api/auth/login", {"email": email, "password": password})
        token = (res or {}).get("access_token")
        if not token:
            raise ApiError(f"Login did not return a token: {res}")
        self.token = token
        return token


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--api-url", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--password", default=None)
    p.add_argument("--token", default=None)
    p.add_argument("--insecure", action="store_true")
    args = p.parse_args()

    client = ApiClient(args.api_url, token=args.token, insecure=args.insecure)
    if not args.token:
        password = args.password or getpass.getpass(f"Password for {args.email}: ")
        client.login(args.email, password)

    replaced, failed = 0, []
    for filename in TARGET_FILES:
        path = FILES_DIR / filename
        if not path.exists():
            failed.append(f"{filename}: missing at {path}")
            continue
        view = compute_view_name(filename)
        try:
            resp = client.post_multipart(
                f"/api/upload/datasources/{view}/replace",
                filename=filename, file_bytes=path.read_bytes(), content_type="text/csv")
            print(f"  ~ replaced {filename} -> {resp}")
            replaced += 1
        except ApiError as e:
            failed.append(f"{filename}: {e}")
            print(f"  ! FAILED {filename}: {e}")

    print(f"\nReplaced {replaced}/{len(TARGET_FILES)} files.")
    if failed:
        print("Failures:")
        for f in failed:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
