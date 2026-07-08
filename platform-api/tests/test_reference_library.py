"""Reference Library tests — permissions, scoping, duplicate detection, bulk validation."""

from __future__ import annotations

import io

from app.auth.jwt import create_access_token
from app.services.reference_library_service import normalize_domain_tag


def _headers(role: str, tenant_id: int = 1, user_id: int = 1) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role=role
    )
    return {"Authorization": f"Bearer {token}"}


# ── unit: domain normalization ───────────────────────────────────────────────


def test_normalize_domain_tag_known() -> None:
    assert normalize_domain_tag("IT & Cybersecurity") == ("IT & Cybersecurity", False)


def test_normalize_domain_tag_alias() -> None:
    assert normalize_domain_tag("cybersecurity") == ("IT & Cybersecurity", False)


def test_normalize_domain_tag_unknown_maps_to_other() -> None:
    domain, remapped = normalize_domain_tag("Totally Made Up")
    assert domain == "Other"
    assert remapped is True


def test_normalize_domain_tag_empty() -> None:
    assert normalize_domain_tag("") == ("Other", True)


# ── meta permissions ─────────────────────────────────────────────────────────


async def test_meta_permissions_root_admin(client) -> None:
    res = await client.get("/api/reference-library/meta", headers=_headers("root_admin"))
    assert res.status_code == 200, res.text
    perms = res.json()["permissions"]
    assert perms["industryWrite"] is True
    assert perms["companyWrite"] is True


async def test_meta_permissions_tenant_admin(client) -> None:
    res = await client.get("/api/reference-library/meta", headers=_headers("tenant_admin"))
    perms = res.json()["permissions"]
    assert perms["industryWrite"] is False
    assert perms["companyWrite"] is True


async def test_meta_permissions_viewer(client) -> None:
    res = await client.get("/api/reference-library/meta", headers=_headers("viewer"))
    perms = res.json()["permissions"]
    assert perms["industryWrite"] is False
    assert perms["companyWrite"] is False


# ── industry tier: create + list + permissions ───────────────────────────────


async def test_industry_create_requires_root_admin(client) -> None:
    res = await client.post(
        "/api/reference-library/documents",
        data={"tier": "industry", "title": "NIST SP 800-161"},
        headers=_headers("tenant_admin"),
    )
    assert res.status_code == 403


async def test_industry_create_and_list(client) -> None:
    res = await client.post(
        "/api/reference-library/documents",
        data={
            "tier": "industry",
            "title": "NIST SP 800-161",
            "issuing_body": "NIST",
            "domain_tag": "IT & Cybersecurity",
        },
        headers=_headers("root_admin"),
    )
    assert res.status_code in (200, 201), res.text
    created = res.json()
    assert created["title"] == "NIST SP 800-161"
    assert created["tier"] == "industry"
    assert created["tenantId"] is None

    res = await client.get(
        "/api/reference-library/documents?tier=industry",
        headers=_headers("viewer", tenant_id=99),
    )
    assert res.status_code == 200
    titles = [d["title"] for d in res.json()["documents"]]
    assert "NIST SP 800-161" in titles  # industry visible to all tenants

    # M4 fast-follow (contract-only): the single-document GET also emits the
    # shared ResponseEnvelope (document mode), additively, keeping the bespoke
    # profile drawer renderer.
    res = await client.get(
        f"/api/reference-library/documents/{created['id']}",
        headers=_headers("viewer", tenant_id=99),
    )
    assert res.status_code == 200, res.text
    doc = res.json()
    assert doc["presentation"]["mode"] == "document"
    assert doc["envelope"]["mode"] == "document"
    assert doc["envelope"]["sections"] == doc["presentation"]["sections"]


# ── company tier: tenant isolation ───────────────────────────────────────────


async def test_company_tier_isolated_by_tenant(client) -> None:
    res = await client.post(
        "/api/reference-library/documents",
        data={"tier": "company", "title": "Acme Supplier Code of Conduct"},
        headers=_headers("tenant_admin", tenant_id=1),
    )
    assert res.status_code in (200, 201), res.text

    # Same tenant sees it.
    res = await client.get(
        "/api/reference-library/documents?tier=company",
        headers=_headers("tenant_admin", tenant_id=1),
    )
    assert "Acme Supplier Code of Conduct" in [d["title"] for d in res.json()["documents"]]

    # Different tenant does NOT see it (data-layer isolation).
    res = await client.get(
        "/api/reference-library/documents?tier=company",
        headers=_headers("tenant_admin", tenant_id=2),
    )
    assert "Acme Supplier Code of Conduct" not in [
        d["title"] for d in res.json()["documents"]
    ]


# ── bulk import validation ───────────────────────────────────────────────────


def _csv_upload(content: str) -> dict:
    return {"file": ("import.csv", io.BytesIO(content.encode()), "text/csv")}


async def test_bulk_validate_classifies_rows(client) -> None:
    csv = (
        "title,source_url,domain_tag,fetch_method\n"
        "Good Doc,https://example.com/a.pdf,IT & Cybersecurity,direct_pdf\n"
        "Paywalled Doc,https://example.com/b.pdf,Finance,paywalled\n"
        "Manual Doc,https://example.com/c.pdf,Legal,manual_required\n"
        ",https://example.com/d.pdf,HR,direct_pdf\n"
        "Bad URL,not-a-url,HR,direct_pdf\n"
    )
    res = await client.post(
        "/api/reference-library/bulk-import/validate",
        files=_csv_upload(csv),
        headers=_headers("root_admin"),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["totalRows"] == 5
    assert body["readyCount"] == 1
    assert body["skippedCount"] == 2  # paywalled + manual_required
    assert body["errorCount"] == 2  # missing title + malformed url
    assert "batchId" in body


async def test_bulk_validate_requires_root_admin(client) -> None:
    csv = "title,source_url\nDoc,https://example.com/a.pdf\n"
    res = await client.post(
        "/api/reference-library/bulk-import/validate",
        files=_csv_upload(csv),
        headers=_headers("tenant_admin"),
    )
    assert res.status_code == 403
