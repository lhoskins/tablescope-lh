"""Unified upload intake: classification, rejection and capabilities."""

from __future__ import annotations

import io
import zipfile

import pytest

from app.auth.jwt import create_access_token
from app.services.file_source_versions import compare_schemas, count_data_rows
from app.services.upload_intake import (
    DESTINATION_DATA_SOURCE,
    DESTINATION_DOCUMENT,
    FAMILY_STRUCTURED,
    UploadRejected,
    accepted_extensions,
    capabilities,
    classify_upload,
)

CSV = b"id,name,amount\n1,Acme,10\n2,Globex,20\n"


def _xlsx_bytes(*, macro: bool = False) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
        if macro:
            archive.writestr("xl/vbaProject.bin", b"\x00\x01")
    return buffer.getvalue()


def _pdf_bytes() -> bytes:
    return b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n"


# ── Classification ────────────────────────────────────────────────────


def test_csv_is_routed_to_a_data_source() -> None:
    result = classify_upload("sales.csv", CSV, "text/csv")
    assert result.destination == DESTINATION_DATA_SOURCE
    assert result.family == FAMILY_STRUCTURED
    assert result.ambiguous is False


def test_xlsx_is_routed_to_a_data_source() -> None:
    result = classify_upload("book.xlsx", _xlsx_bytes())
    assert result.destination == DESTINATION_DATA_SOURCE


def test_pdf_is_routed_to_documents() -> None:
    result = classify_upload("policy.pdf", _pdf_bytes(), "application/pdf")
    assert result.destination == DESTINATION_DOCUMENT


def test_record_shaped_json_is_routed_to_a_data_source() -> None:
    result = classify_upload("rows.json", b'[{"a": 1}, {"a": 2}]', "application/json")
    assert result.destination == DESTINATION_DATA_SOURCE
    assert result.reason


def test_narrative_json_is_routed_to_documents() -> None:
    result = classify_upload("config.json", b'{"title": "notes"}', "application/json")
    assert result.destination == DESTINATION_DOCUMENT
    assert result.ambiguous is True
    assert result.alternatives == [DESTINATION_DATA_SOURCE, DESTINATION_DOCUMENT]


def test_delimited_text_is_routed_to_a_data_source() -> None:
    result = classify_upload("rows.txt", b"a,b\n1,2\n3,4\n", "text/plain")
    assert result.destination == DESTINATION_DATA_SOURCE


def test_prose_text_is_routed_to_documents() -> None:
    result = classify_upload("memo.txt", b"Quarterly notes.\nNothing tabular here.\n", "text/plain")
    assert result.destination == DESTINATION_DOCUMENT


def test_repeated_xml_records_route_to_a_data_source() -> None:
    xml = b"<rows><row><a>1</a></row><row><a>2</a></row></rows>"
    assert classify_upload("rows.xml", xml, "application/xml").destination == DESTINATION_DATA_SOURCE


def test_xml_with_a_doctype_is_never_parsed() -> None:
    xml = b'<!DOCTYPE r [<!ENTITY x "boom">]><rows><row/><row/></rows>'
    result = classify_upload("evil.xml", xml, "application/xml")
    assert result.destination == DESTINATION_DOCUMENT


# ── Rejections ────────────────────────────────────────────────────────


def test_unsupported_extension_is_rejected() -> None:
    with pytest.raises(UploadRejected) as exc:
        classify_upload("payload.exe", b"MZ\x90\x00")
    assert exc.value.code == "unsupported_type"


def test_macro_enabled_extension_is_rejected() -> None:
    with pytest.raises(UploadRejected) as exc:
        classify_upload("book.xlsm", _xlsx_bytes(macro=True))
    assert exc.value.code == "macro_enabled"


def test_macro_payload_inside_an_xlsx_is_rejected() -> None:
    with pytest.raises(UploadRejected) as exc:
        classify_upload("book.xlsx", _xlsx_bytes(macro=True))
    assert exc.value.code == "macro_enabled"


def test_renamed_pdf_is_rejected() -> None:
    with pytest.raises(UploadRejected) as exc:
        classify_upload("sales.csv", _pdf_bytes())
    assert exc.value.code == "signature_mismatch"


def test_xlsx_without_office_content_is_rejected() -> None:
    with pytest.raises(UploadRejected) as exc:
        classify_upload("fake.xlsx", CSV)
    assert exc.value.code == "signature_mismatch"


def test_mime_mismatch_is_rejected() -> None:
    with pytest.raises(UploadRejected) as exc:
        classify_upload("sales.csv", CSV, "application/pdf")
    assert exc.value.code == "mime_mismatch"


def test_encrypted_pdf_is_rejected() -> None:
    with pytest.raises(UploadRejected) as exc:
        classify_upload("locked.pdf", b"%PDF-1.7\n/Encrypt 12 0 R\n", "application/pdf")
    assert exc.value.code == "encrypted"


def test_empty_file_is_rejected() -> None:
    with pytest.raises(UploadRejected) as exc:
        classify_upload("sales.csv", b"")
    assert exc.value.code == "empty_file"


def test_oversized_file_is_rejected() -> None:
    with pytest.raises(UploadRejected) as exc:
        classify_upload("sales.csv", CSV, max_bytes=4)
    assert exc.value.code == "too_large"


# ── Schema comparison ─────────────────────────────────────────────────


def _cols(**fields: str) -> list[dict[str, str]]:
    return [{"field": name, "type": type_} for name, type_ in fields.items()]


def test_added_columns_are_compatible() -> None:
    diff = compare_schemas(_cols(id="number"), _cols(id="number", name="string"))
    assert diff["compatible"] is True
    assert diff["addedColumns"] == ["name"]


def test_removed_columns_block_activation() -> None:
    diff = compare_schemas(_cols(id="number", name="string"), _cols(id="number"))
    assert diff["compatible"] is False
    assert diff["removedColumns"] == ["name"]


def test_type_changes_block_activation() -> None:
    diff = compare_schemas(_cols(amount="number"), _cols(amount="string"))
    assert diff["compatible"] is False
    assert diff["typeChangedColumns"] == [
        {"column": "amount", "from": "number", "to": "string"}
    ]
    assert diff["removedColumns"] == []


def test_identical_schemas_are_compatible() -> None:
    diff = compare_schemas(_cols(id="number"), _cols(id="number"))
    assert diff == {
        "addedColumns": [],
        "removedColumns": [],
        "typeChangedColumns": [],
        "blockers": [],
        "compatible": True,
    }


def test_csv_rows_are_counted_without_the_header() -> None:
    assert count_data_rows(CSV, "sales.csv") == 2


# ── Capability endpoint ───────────────────────────────────────────────


def test_capabilities_cover_structured_and_document_formats() -> None:
    extensions = accepted_extensions()
    assert {".csv", ".xlsx", ".pdf", ".docx", ".pptx"} <= set(extensions)
    assert capabilities()["maxFileSizeBytes"] > 0


@pytest.mark.asyncio
async def test_capabilities_endpoint_is_the_source_of_truth(client) -> None:
    token = create_access_token(sub="u", tenant_id=1, user_id=1, role="viewer")
    resp = await client.get(
        "/api/uploads/capabilities", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["maxFileSizeBytes"] == capabilities()["maxFileSizeBytes"]
    assert [item["extension"] for item in body["accepted"]] == accepted_extensions()


@pytest.mark.asyncio
async def test_classify_endpoint_reports_the_destination(client) -> None:
    token = create_access_token(sub="u", tenant_id=1, user_id=1, role="editor")
    resp = await client.post(
        "/api/uploads/classify",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("sales.csv", CSV, "text/csv")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["destination"] == DESTINATION_DATA_SOURCE
    assert body["fileName"] == "sales.csv"
    assert body["checksum"]


@pytest.mark.asyncio
async def test_classify_endpoint_rejects_unsupported_files(client) -> None:
    token = create_access_token(sub="u", tenant_id=1, user_id=1, role="editor")
    resp = await client.post(
        "/api/uploads/classify",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("payload.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "unsupported_type"


@pytest.mark.asyncio
async def test_classify_endpoint_requires_authentication(client) -> None:
    resp = await client.post(
        "/api/uploads/classify", files={"file": ("sales.csv", CSV, "text/csv")}
    )
    assert resp.status_code in (401, 403)
