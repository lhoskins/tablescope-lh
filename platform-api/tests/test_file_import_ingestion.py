"""Ingestion equivalence, validation, and job lifecycle for file imports.

The central guarantee of this feature is that *how* bytes arrive is
irrelevant: identical bytes from a local upload, an HTTPS URL, and an SMB
share must produce the same hash, the same staged contract, and the same
preview payload, differing only in provenance.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app.config import get_settings
from app.models.file_import_job import FileImportJob
from app.models.network_file_connection import NetworkFileConnection
from app.models.tenant import Tenant
from app.models.user import User
from app.services import file_ingestion, malware_scan, smb_gateway
from app.services.file_ingestion import FileImportError
from app.services.file_validation import FileValidationError, validate_content

CSV = b"region,units\nnorth,10\nsouth,12\n"
T1, U1 = 1, 1


@pytest.fixture(autouse=True)
def _settings(tmp_path, monkeypatch):
    monkeypatch.setenv("FILE_IMPORT_QUARANTINE_PATH", str(tmp_path / "quarantine"))
    monkeypatch.setenv("FILE_IMPORT_NETWORK_ENABLED", "true")
    monkeypatch.setenv("FILE_IMPORT_ALLOWED_SMB_HOSTS", "fileserver")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def seeded(db_session):
    db_session.add(Tenant(id=T1, name="Acme", slug="acme"))
    db_session.add(User(id=U1, tenant_id=T1, email="a@example.com"))
    await db_session.flush()
    return db_session


def _connection() -> NetworkFileConnection:
    return NetworkFileConnection(
        id=7,
        tenant_id=T1,
        name="Finance",
        host="fileserver",
        share_name="data",
        approved_root_path="finance",
        enabled=True,
        archived=False,
    )


def _mock_url_fetch(monkeypatch, content: bytes = CSV, *, filename="sales.csv"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=content, headers={"content-type": "text/csv"}
        )

    real = file_ingestion.fetch_remote_file

    async def patched(url, **kwargs):
        kwargs.setdefault("resolver", lambda host, port: ["93.184.216.34"])
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return await real(url, **kwargs)

    monkeypatch.setattr(file_ingestion, "fetch_remote_file", patched)
    return f"https://files.example.com/reports/{filename}?token=secret"


# ── Acquisition equivalence ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_local_url_and_network_produce_identical_staged_content(
    seeded, monkeypatch
):
    url = _mock_url_fetch(monkeypatch)
    monkeypatch.setattr(
        smb_gateway, "read_network_file", lambda *a, **k: _async(CSV)
    )
    monkeypatch.setattr(
        file_ingestion, "read_network_file", lambda *a, **k: _async(CSV)
    )

    _, local = await file_ingestion.acquire_local_upload(
        seeded, tenant_id=T1, user_id=U1, project_id=None,
        filename="sales.csv", data=CSV, content_type="text/csv",
    )
    _, remote = await file_ingestion.acquire_url(
        seeded, tenant_id=T1, user_id=U1, project_id=None, url=url
    )
    _, network = await file_ingestion.acquire_network_path(
        seeded, tenant_id=T1, user_id=U1, project_id=None,
        connection=_connection(), path=r"\\fileserver\data\finance\sales.csv",
    )

    expected = hashlib.sha256(CSV).hexdigest()
    for staged in (local, remote, network):
        assert staged.sha256 == expected
        assert staged.content_family == "tabular"
        assert staged.detected_extension == "csv"
        assert staged.sanitized_filename == "sales.csv"
        assert staged.content_path.read_bytes() == CSV

    assert local.acquisition_method == "local_upload"
    assert remote.acquisition_method == "url"
    assert network.acquisition_method == "network_path"


def _async(value):
    async def _run():
        return value

    return _run()


@pytest.mark.asyncio
async def test_url_provenance_is_redacted(seeded, monkeypatch):
    url = _mock_url_fetch(monkeypatch)
    job, _ = await file_ingestion.acquire_url(
        seeded, tenant_id=T1, user_id=U1, project_id=None, url=url
    )
    assert job.source_host == "files.example.com"
    assert "secret" not in (job.source_locator_redacted or "")
    assert job.source_locator_redacted == "https://files.example.com/reports/sales.csv"


@pytest.mark.asyncio
async def test_network_provenance_hides_folders(seeded, monkeypatch):
    monkeypatch.setattr(
        file_ingestion, "read_network_file", lambda *a, **k: _async(CSV)
    )
    job, _ = await file_ingestion.acquire_network_path(
        seeded, tenant_id=T1, user_id=U1, project_id=None,
        connection=_connection(),
        path=r"\\fileserver\data\finance\merger-2026\sales.csv",
    )
    assert job.network_connection_id == 7
    assert "merger-2026" not in (job.source_locator_redacted or "")


@pytest.mark.asyncio
async def test_network_import_refused_when_disabled(seeded, monkeypatch):
    monkeypatch.setenv("FILE_IMPORT_NETWORK_ENABLED", "false")
    get_settings.cache_clear()
    with pytest.raises(FileImportError) as exc:
        await file_ingestion.acquire_network_path(
            seeded, tenant_id=T1, user_id=U1, project_id=None,
            connection=_connection(), path=r"\\fileserver\data\finance\sales.csv",
        )
    assert exc.value.code == "NETWORK_IMPORT_DISABLED"


@pytest.mark.asyncio
async def test_connection_from_another_tenant_is_refused(seeded):
    other = _connection()
    other.tenant_id = 999
    with pytest.raises(FileImportError) as exc:
        await file_ingestion.acquire_network_path(
            seeded, tenant_id=T1, user_id=U1, project_id=None,
            connection=other, path=r"\\fileserver\data\finance\sales.csv",
        )
    assert exc.value.code == "CONNECTION_NOT_FOUND"


@pytest.mark.asyncio
async def test_url_import_refused_when_disabled(seeded, monkeypatch):
    monkeypatch.setenv("FILE_IMPORT_URL_ENABLED", "false")
    get_settings.cache_clear()
    with pytest.raises(FileImportError) as exc:
        await file_ingestion.acquire_url(
            seeded, tenant_id=T1, user_id=U1, project_id=None,
            url="https://files.example.com/a.csv",
        )
    assert exc.value.code == "URL_IMPORT_DISABLED"


@pytest.mark.asyncio
async def test_oversized_file_is_refused(seeded, monkeypatch):
    monkeypatch.setenv("FILE_IMPORT_MAX_BYTES", "16")
    get_settings.cache_clear()
    with pytest.raises(FileImportError) as exc:
        await file_ingestion.acquire_local_upload(
            seeded, tenant_id=T1, user_id=U1, project_id=None,
            filename="sales.csv", data=CSV,
        )
    assert exc.value.code == "FILE_TOO_LARGE"


# ── Content validation ───────────────────────────────────────────────────


def test_executable_disguised_as_csv_is_refused():
    with pytest.raises(FileValidationError) as exc:
        validate_content(b"MZ\x90\x00" + b"\x00" * 64, "payload.csv")
    assert exc.value.code == "FORBIDDEN_CONTENT"


def test_archive_is_refused():
    with pytest.raises(FileValidationError) as exc:
        validate_content(b"\x1f\x8b\x08\x00data", "bundle.csv")
    assert exc.value.code == "FORBIDDEN_CONTENT"


def test_xlsx_extension_without_zip_signature_is_refused():
    with pytest.raises(FileValidationError) as exc:
        validate_content(b"region,units\n1,2\n", "sales.xlsx")
    assert exc.value.code == "SIGNATURE_MISMATCH"


def test_mime_type_mismatch_is_refused():
    with pytest.raises(FileValidationError) as exc:
        validate_content(CSV, "sales.csv", declared_mime_type="application/pdf")
    assert exc.value.code == "MIME_MISMATCH"


def test_document_is_refused_where_only_tabular_is_allowed():
    with pytest.raises(FileValidationError) as exc:
        validate_content(
            b"%PDF-1.4 body", "report.pdf", allowed_families=("tabular",)
        )
    assert exc.value.code == "UNSUPPORTED_TYPE"


def test_document_family_is_recognised():
    result = validate_content(b"%PDF-1.4 body", "report.pdf")
    assert result.content_family == "document"


# ── Malware scanning policy ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scanner_unavailable_fails_closed(seeded, monkeypatch):
    monkeypatch.setenv("FILE_IMPORT_MALWARE_SCAN_ENABLED", "true")
    monkeypatch.setenv("FILE_IMPORT_MALWARE_SCAN_HOST", "127.0.0.1")
    monkeypatch.setenv("FILE_IMPORT_MALWARE_SCAN_PORT", "1")
    get_settings.cache_clear()
    with pytest.raises(FileImportError) as exc:
        await file_ingestion.acquire_local_upload(
            seeded, tenant_id=T1, user_id=U1, project_id=None,
            filename="sales.csv", data=CSV,
        )
    assert exc.value.code == "SCANNER_UNAVAILABLE"


@pytest.mark.asyncio
async def test_scanner_unavailable_can_fail_open_when_operators_choose(monkeypatch):
    monkeypatch.setenv("FILE_IMPORT_MALWARE_SCAN_ENABLED", "true")
    monkeypatch.setenv("FILE_IMPORT_MALWARE_SCAN_HOST", "127.0.0.1")
    monkeypatch.setenv("FILE_IMPORT_MALWARE_SCAN_PORT", "1")
    monkeypatch.setenv("FILE_IMPORT_MALWARE_SCAN_FAIL_OPEN", "true")
    get_settings.cache_clear()
    result = await malware_scan.scan_bytes(CSV)
    assert result.status == "unavailable"
    assert not result.is_blocking


@pytest.mark.asyncio
async def test_infected_file_is_blocked_and_not_staged(seeded, monkeypatch):
    async def infected(_data):
        return malware_scan.ScanResult(status="infected", signature="Eicar-Test")

    monkeypatch.setattr(malware_scan, "scan_bytes", infected)
    with pytest.raises(FileImportError) as exc:
        await file_ingestion.acquire_local_upload(
            seeded, tenant_id=T1, user_id=U1, project_id=None,
            filename="sales.csv", data=CSV,
        )
    assert exc.value.code == "SECURITY_BLOCKED"
    quarantine = Path(get_settings().file_import_quarantine_path)
    assert not list(quarantine.rglob("sales.csv"))


# ── Job lifecycle ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_job_lookup_is_tenant_and_requester_scoped(seeded):
    job, _ = await file_ingestion.acquire_local_upload(
        seeded, tenant_id=T1, user_id=U1, project_id=None,
        filename="sales.csv", data=CSV,
    )
    assert await file_ingestion.get_job_for_user(
        seeded, job.id, tenant_id=T1, user_id=U1
    )
    assert (
        await file_ingestion.get_job_for_user(
            seeded, job.id, tenant_id=2, user_id=U1
        )
        is None
    )
    assert (
        await file_ingestion.get_job_for_user(
            seeded, job.id, tenant_id=T1, user_id=99
        )
        is None
    )


@pytest.mark.asyncio
async def test_discarding_quarantine_removes_bytes_and_is_idempotent(seeded):
    job, staged = await file_ingestion.acquire_local_upload(
        seeded, tenant_id=T1, user_id=U1, project_id=None,
        filename="sales.csv", data=CSV,
    )
    assert staged.content_path.is_file()
    file_ingestion.discard_quarantine(job)
    assert not staged.content_path.exists()
    assert job.storage_key is None
    file_ingestion.discard_quarantine(job)  # no error on a second call
    with pytest.raises(FileImportError) as exc:
        file_ingestion.read_staged_bytes(job)
    assert exc.value.code == "STAGED_FILE_MISSING"


@pytest.mark.asyncio
async def test_expired_jobs_are_swept_and_their_bytes_deleted(seeded):
    job, staged = await file_ingestion.acquire_local_upload(
        seeded, tenant_id=T1, user_id=U1, project_id=None,
        filename="sales.csv", data=CSV,
    )
    job.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await seeded.flush()

    swept = await file_ingestion.cleanup_expired_jobs(seeded)
    assert swept == 1
    assert job.status == "expired"
    assert not staged.content_path.exists()


@pytest.mark.asyncio
async def test_completed_jobs_are_not_expired(seeded):
    job, _ = await file_ingestion.acquire_local_upload(
        seeded, tenant_id=T1, user_id=U1, project_id=None,
        filename="sales.csv", data=CSV,
    )
    job.status = "completed"
    job.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await seeded.flush()
    assert await file_ingestion.cleanup_expired_jobs(seeded) == 0


@pytest.mark.asyncio
async def test_job_survives_a_new_session(db_engine, seeded):
    """Import state lives in Postgres, not a process-local dict."""
    job, _ = await file_ingestion.acquire_local_upload(
        seeded, tenant_id=T1, user_id=U1, project_id=None,
        filename="sales.csv", data=CSV,
    )
    job_id = job.id
    await seeded.commit()

    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as fresh:
        reloaded = await fresh.get(FileImportJob, job_id)
        assert reloaded is not None
        assert reloaded.sha256 == hashlib.sha256(CSV).hexdigest()
        assert Path(reloaded.storage_key or "").read_bytes() == CSV


@pytest.mark.asyncio
async def test_client_payload_carries_no_sensitive_locator(seeded, monkeypatch):
    url = _mock_url_fetch(monkeypatch)
    job, _ = await file_ingestion.acquire_url(
        seeded, tenant_id=T1, user_id=U1, project_id=None, url=url
    )
    payload = job.to_dict()
    rendered = repr(payload)
    assert "secret" not in rendered
    assert "storage_key" not in payload
