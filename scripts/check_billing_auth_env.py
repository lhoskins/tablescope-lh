#!/usr/bin/env python3
"""Doctor script for Supabase Auth + Stripe Billing configuration.

Verifies that the required environment variables are present and that the
configured Supabase and Stripe credentials actually work — WITHOUT ever
printing secret values.

Usage:
    python scripts/check_billing_auth_env.py [--env-file platform-api/.env]
                                             [--skip-connectivity]

Exit code 0 = all good, non-zero = one or more problems found.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    import httpx
except ImportError:  # pragma: no cover - httpx is a platform-api dependency
    httpx = None  # type: ignore[assignment]


# Variables that must always be present for the billing/auth stack to work.
REQUIRED = [
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "NEXT_PUBLIC_SUPABASE_URL",
    "NEXT_PUBLIC_SUPABASE_ANON_KEY",
    "STRIPE_MODE",
    "STRIPE_SECRET_KEY",
    "STRIPE_PUBLISHABLE_KEY",
    "NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY",
    "STRIPE_SUCCESS_URL",
    "STRIPE_CANCEL_URL",
]

# Present-but-may-be-empty-until-later variables.
OPTIONAL = [
    "APP_ENV",
    "ENVIRONMENT",
    "SUPABASE_ENV",
    "SUPABASE_PROJECT_REF",
    "SUPABASE_DATABASE_URL",
    "SUPABASE_JWT_SECRET",
    "STRIPE_WEBHOOK_SECRET",  # filled in after the webhook is created
]

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"{GREEN}[ ok ]{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"{YELLOW}[warn]{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"{RED}[fail]{RESET} {msg}")


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ (no overwrite)."""
    if not path.exists():
        warn(f"env file {path} not found; relying on process environment")
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    ok(f"loaded env file {path}")


def check_presence() -> list[str]:
    problems: list[str] = []
    for name in REQUIRED:
        value = os.environ.get(name, "").strip()
        if value:
            ok(f"{name} is set")
        else:
            fail(f"{name} is MISSING")
            problems.append(name)
    for name in OPTIONAL:
        value = os.environ.get(name, "").strip()
        if value:
            ok(f"{name} is set")
        else:
            warn(f"{name} is not set (optional / set later)")
    return problems


def check_env_safety() -> list[str]:
    problems: list[str] = []
    app_env = (os.environ.get("APP_ENV") or os.environ.get("ENVIRONMENT") or "development").lower()
    stripe_mode = (os.environ.get("STRIPE_MODE") or "").lower()
    supabase_env = (os.environ.get("SUPABASE_ENV") or "").lower()
    stripe_secret = os.environ.get("STRIPE_SECRET_KEY", "")

    # Billing safety is keyed off STRIPE_MODE (not the global APP_ENV) so a
    # production host can run billing in test mode during rollout.
    if stripe_mode == "live" and stripe_secret.startswith("sk_test_"):
        fail("STRIPE_MODE=live but a Stripe TEST secret key is set")
        problems.append("STRIPE_SECRET_KEY")
    elif stripe_mode == "test" and stripe_secret.startswith("sk_live_"):
        fail("STRIPE_MODE=test but a Stripe LIVE secret key is set")
        problems.append("STRIPE_SECRET_KEY")
    elif stripe_mode == "live" and app_env != "production":
        fail(f"Stripe LIVE mode used while APP_ENV={app_env} (must be production)")
        problems.append("STRIPE_MODE")
    elif stripe_secret:
        ok(f"env safety: APP_ENV={app_env}, STRIPE_MODE={stripe_mode or 'unset'} consistent")
    if supabase_env == "production" and app_env != "production":
        warn(f"SUPABASE_ENV=production while APP_ENV={app_env}")
    return problems


def check_stripe() -> list[str]:
    problems: list[str] = []
    secret = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not secret:
        warn("skipping Stripe connectivity (STRIPE_SECRET_KEY missing)")
        return problems
    if httpx is None:
        warn("httpx not installed; skipping Stripe connectivity check")
        return problems
    try:
        resp = httpx.get(
            "https://api.stripe.com/v1/account",
            auth=(secret, ""),
            timeout=15.0,
        )
    except Exception as exc:
        fail(f"Stripe connectivity error: {type(exc).__name__}")
        problems.append("STRIPE_SECRET_KEY")
        return problems
    if resp.status_code == 200:
        # Report non-secret metadata only.
        livemode = resp.json().get("charges_enabled")
        ok(f"Stripe API reachable (account ok, charges_enabled={livemode})")
    elif resp.status_code in (401, 403):
        fail("Stripe rejected the secret key (401/403)")
        problems.append("STRIPE_SECRET_KEY")
    else:
        fail(f"Stripe API returned HTTP {resp.status_code}")
        problems.append("STRIPE_SECRET_KEY")
    return problems


def check_supabase() -> list[str]:
    problems: list[str] = []
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    anon = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    service = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url:
        warn("skipping Supabase connectivity (SUPABASE_URL missing)")
        return problems
    if httpx is None:
        warn("httpx not installed; skipping Supabase connectivity check")
        return problems

    # Auth health endpoint requires no key.
    try:
        health = httpx.get(f"{url}/auth/v1/health", timeout=15.0)
        if health.status_code == 200:
            ok("Supabase Auth (GoTrue) reachable")
        else:
            warn(f"Supabase /auth/v1/health returned HTTP {health.status_code}")
    except Exception as exc:
        fail(f"Supabase connectivity error: {type(exc).__name__}")
        problems.append("SUPABASE_URL")
        return problems

    # Service role key: list users (admin API). Confirms the key is valid.
    if service:
        try:
            resp = httpx.get(
                f"{url}/auth/v1/admin/users?page=1&per_page=1",
                headers={"apikey": service, "Authorization": f"Bearer {service}"},
                timeout=15.0,
            )
            if resp.status_code == 200:
                ok("Supabase service role key valid (admin users API)")
            elif resp.status_code in (401, 403):
                fail("Supabase rejected the SERVICE_ROLE key (401/403)")
                problems.append("SUPABASE_SERVICE_ROLE_KEY")
            else:
                warn(f"Supabase admin API returned HTTP {resp.status_code}")
        except Exception as exc:
            fail(f"Supabase admin API error: {type(exc).__name__}")
            problems.append("SUPABASE_SERVICE_ROLE_KEY")

    # Anon key: REST root should respond (200/404 acceptable, 401 = bad key).
    if anon:
        try:
            resp = httpx.get(
                f"{url}/rest/v1/",
                headers={"apikey": anon, "Authorization": f"Bearer {anon}"},
                timeout=15.0,
            )
            if resp.status_code in (200, 404):
                ok("Supabase anon key accepted by REST endpoint")
            elif resp.status_code in (401, 403):
                fail("Supabase rejected the ANON key (401/403)")
                problems.append("SUPABASE_ANON_KEY")
            else:
                warn(f"Supabase REST returned HTTP {resp.status_code}")
        except Exception as exc:
            warn(f"Supabase REST check error: {type(exc).__name__}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        default="platform-api/.env",
        help="Path to a .env file to load (default: platform-api/.env)",
    )
    parser.add_argument(
        "--skip-connectivity",
        action="store_true",
        help="Only check presence + env safety; skip network calls.",
    )
    args = parser.parse_args()

    print("== Tablescope billing/auth environment check ==\n")
    load_env_file(Path(args.env_file))

    problems: list[str] = []
    print("\n-- required/optional variables --")
    problems += check_presence()
    print("\n-- environment safety --")
    problems += check_env_safety()

    if not args.skip_connectivity:
        print("\n-- Stripe connectivity --")
        problems += check_stripe()
        print("\n-- Supabase connectivity --")
        problems += check_supabase()

    print()
    unique = sorted(set(problems))
    if unique:
        fail(f"{len(unique)} problem(s): {', '.join(unique)}")
        return 1
    ok("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
