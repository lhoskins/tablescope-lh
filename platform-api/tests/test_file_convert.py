"""Tests for JSON/XML -> CSV conversion used by the upload pipeline (item 4)."""

from __future__ import annotations

import csv
import io

from app.services.file_sources import convert_to_csv_if_needed, display_source


def test_display_source_preserves_original_format() -> None:
    # JSON/XML are stored on disk as .csv but should display their real type.
    assert display_source("people.csv", "json") == ("people.json", "json")
    assert display_source("orders.csv", "xml") == ("orders.xml", "xml")


def test_display_source_falls_back_to_disk_extension() -> None:
    assert display_source("sales.csv", None) == ("sales.csv", "csv")
    assert display_source("report.xlsx", None) == ("report.xlsx", "xlsx")
    assert display_source("noext", None) == ("noext", "file")


def _parse(content: bytes) -> tuple[list[str], list[list[str]]]:
    reader = csv.reader(io.StringIO(content.decode("utf-8")))
    rows = list(reader)
    return rows[0], rows[1:]


def test_non_json_xml_passthrough() -> None:
    name, content = convert_to_csv_if_needed("data.csv", b"a,b\n1,2")
    assert name == "data.csv"
    assert content == b"a,b\n1,2"


def test_json_array_of_objects() -> None:
    name, content = convert_to_csv_if_needed(
        "people.json", b'[{"id":1,"name":"A"},{"id":2,"name":"B"}]'
    )
    assert name == "people.csv"
    header, data = _parse(content)
    assert header == ["id", "name"]
    assert data == [["1", "A"], ["2", "B"]]


def test_json_wrapper_object_uses_nested_list() -> None:
    _, content = convert_to_csv_if_needed(
        "w.json", b'{"results":[{"a":1,"b":2},{"a":3,"b":4}]}'
    )
    header, data = _parse(content)
    assert header == ["a", "b"]
    assert data == [["1", "2"], ["3", "4"]]


def test_json_nested_value_is_serialized() -> None:
    _, content = convert_to_csv_if_needed(
        "t.json", b'[{"id":1,"tags":["x","y"]}]'
    )
    header, data = _parse(content)
    assert header == ["id", "tags"]
    assert data[0][0] == "1"
    assert "x" in data[0][1] and "y" in data[0][1]


def test_xml_repeating_elements_become_rows() -> None:
    name, content = convert_to_csv_if_needed(
        "rows.xml",
        b"<rows><row><id>1</id><name>A</name></row>"
        b"<row><id>2</id><name>B</name></row></rows>",
    )
    assert name == "rows.csv"
    header, data = _parse(content)
    assert header == ["id", "name"]
    assert data == [["1", "A"], ["2", "B"]]


def test_xml_attributes_become_columns() -> None:
    _, content = convert_to_csv_if_needed(
        "a.xml",
        b'<items><item id="1" name="A"/><item id="2" name="B"/></items>',
    )
    header, data = _parse(content)
    assert set(header) == {"id", "name"}
    assert len(data) == 2


def test_invalid_json_raises_value_error() -> None:
    try:
        convert_to_csv_if_needed("bad.json", b"{not json")
    except ValueError as exc:
        assert "JSON" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
