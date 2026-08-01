#!/usr/bin/env python3
"""Demo Company Installer for Tablescope.

Generates a complete, reproducible synthetic company (structured datasets +
unstructured business documents) and, optionally, loads it into a Tablescope
tenant: one project per department (owned by the authenticated user), each CSV
uploaded as a data source (auto-creating a saved query and triggering AI
processing) and each document uploaded as an AI-processed asset.

Examples
--------
Generate only (no API calls)::

    python scripts/install_demo_company.py \\
        --company Simplicit --industry Manufacturing --size Enterprise \\
        --seed 42 --generate-only

Preview the load plan without uploading::

    python scripts/install_demo_company.py --dry-run

Upload a small sample, then everything (needs API URL + owner credentials)::

    python scripts/install_demo_company.py --sample \\
        --api-url https://app.example.com --email owner@example.com
    python scripts/install_demo_company.py --all \\
        --api-url https://app.example.com --email owner@example.com
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo_company import config as C  # noqa: E402
from demo_company.datasets import generate_datasets  # noqa: E402
from demo_company.dictionaries import generate_docs  # noqa: E402
from demo_company.dimensions import build_dimensions  # noqa: E402
from demo_company.documents import generate_documents  # noqa: E402
from demo_company.importer import ApiClient, ApiError, DemoImporter  # noqa: E402
from demo_company.io_utils import Registry  # noqa: E402
from demo_company.manifest import build_manifest, load_manifest  # noqa: E402


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="install_demo_company.py",
        description="Generate and load a synthetic demo company into Tablescope.")
    p.add_argument("--company", default="Simplicit")
    p.add_argument("--display-name", default=None,
                   help="Human-facing company name (default: '<company> Demo Company').")
    p.add_argument("--industry", default="Manufacturing")
    p.add_argument("--size", default="Enterprise", choices=sorted(C.SIZE_PROFILES))
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output", default=None,
                   help="Output root (default: scripts/demo_company/output/<slug>).")

    mode = p.add_argument_group("mode")
    mode.add_argument("--generate-only", action="store_true",
                      help="Only generate files; do not contact the API.")
    mode.add_argument("--dry-run", action="store_true",
                      help="Generate + print the load plan without uploading.")
    mode.add_argument("--sample", action="store_true",
                      help="Upload only the small sample subset.")
    mode.add_argument("--all", action="store_true",
                      help="Upload everything.")
    mode.add_argument("--refresh-existing", action="store_true",
                      help="Replace already-uploaded CSV data sources with "
                           "freshly generated data instead of skipping them "
                           "(same file name; the new file's columns must be "
                           "a superset of what's already loaded). Documents "
                           "and Company Library assets are never affected — "
                           "their content doesn't depend on the calendar "
                           "window, so re-uploading them is unnecessary.")

    api = p.add_argument_group("api")
    api.add_argument("--api-url", default=os.environ.get("TABLESCOPE_API_URL"))
    api.add_argument("--email", default=os.environ.get("TABLESCOPE_EMAIL"))
    api.add_argument("--password", default=os.environ.get("TABLESCOPE_PASSWORD"))
    api.add_argument("--token", default=os.environ.get("TABLESCOPE_TOKEN"))
    api.add_argument("--insecure", action="store_true",
                     help="Skip TLS certificate verification.")
    api.add_argument("--no-shared", action="store_true",
                     help="Create projects private instead of shared.")
    p.add_argument("--quiet", action="store_true")
    return p.parse_args(argv)


def _spec(args: argparse.Namespace) -> C.CompanySpec:
    display = args.display_name or f"{args.company} Demo Company"
    return C.CompanySpec(company=args.company, display_name=display,
                         industry=args.industry, size=args.size, seed=args.seed)


def generate(spec: C.CompanySpec, out_root: Path, owner_email: str,
             verbose: bool) -> Registry:
    dims = build_dimensions(spec)
    reg = Registry(out_root)
    generate_datasets(reg, dims)
    generate_documents(reg, dims)
    generate_docs(reg, dims)  # README + dictionaries + answer key
    build_manifest(reg, spec, owner_email)
    if verbose:
        csvs = reg.csv_artifacts()
        docs = reg.doc_artifacts()
        print(f"Generated {len(csvs)} CSV datasets "
              f"({sum(a.rows for a in csvs):,} rows) and {len(docs)} documents.")
        print(f"Output: {out_root}")
        print(f"Manifest: {out_root / 'manifest.yaml'}")
    return reg


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    verbose = not args.quiet
    spec = _spec(args)

    out_root = Path(args.output) if args.output else (
        Path(__file__).resolve().parent / "demo_company" / "output" / spec.slug)
    out_root.mkdir(parents=True, exist_ok=True)

    owner_email = args.email or "owner@example.com"
    generate(spec, out_root, owner_email, verbose)

    if args.generate_only:
        return 0

    upload = args.sample or args.all
    if not upload and not args.dry_run:
        if verbose:
            print("\nNo load mode selected (use --dry-run, --sample, or --all "
                  "to load into Tablescope).")
        return 0

    manifest = load_manifest(out_root / "manifest.yaml")

    if args.dry_run:
        importer = DemoImporter(ApiClient(""), manifest, out_root,
                                dry_run=True, sample=args.sample, verbose=verbose,
                                refresh=args.refresh_existing)
        report = importer.run()
        print("\n" + report.summary())
        return 0

    # Live upload: need API URL + auth.
    if not args.api_url:
        print("error: --api-url is required for --sample/--all (or set "
              "TABLESCOPE_API_URL).", file=sys.stderr)
        return 2
    client = ApiClient(args.api_url, token=args.token, insecure=args.insecure)
    if not args.token:
        if not args.email:
            print("error: --email (or --token) is required to authenticate.",
                  file=sys.stderr)
            return 2
        password = args.password or getpass.getpass(f"Password for {args.email}: ")
        try:
            client.login(args.email, password)
        except ApiError as e:
            print(f"error: login failed: {e}", file=sys.stderr)
            return 1
    importer = DemoImporter(client, manifest, out_root, sample=args.sample,
                            shared=not args.no_shared, verbose=verbose,
                            refresh=args.refresh_existing)
    try:
        report = importer.run()
    except ApiError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print("\n" + report.summary())
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
