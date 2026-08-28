"""Tests for AI grounding profile summaries (data_source_profiler.py).

Covers the exact bug this module fixes: the AI SQL generator and "why"
investigation planner previously saw only a source's name and columns, never
its actual row count, date range, or categorical values -- so it invented
columns, guessed date filters the data couldn't satisfy, and reasoned about a
"rising trend" over a single month of data.
"""

from __future__ import annotations

from app.models.data_source_ai_profile import DataSourceAIProfile, DataSourceFieldProfile
from app.models.file_source_meta import FileSourceMeta
from app.services.data_source_profiler import profile_sources


def _source(source_id: int, view_name: str, columns: list[tuple[str, str]]) -> FileSourceMeta:
    return FileSourceMeta(
        id=source_id,
        tenant_id=1,
        owner_id=1,
        project_id=1,
        view_name=view_name,
        file_name=f"{view_name}.csv",
        vdb_type="user",
        archived=False,
        column_types=[{"name": name, "type": col_type} for name, col_type in columns],
    )


async def _seed_profile(
    db_session,
    *,
    data_source_id: int,
    row_count: int,
    fields: list[dict],
) -> None:
    profile = DataSourceAIProfile(
        data_source_id=data_source_id,
        tenant_id=1,
        row_count=row_count,
        status="analyzed",
    )
    db_session.add(profile)
    await db_session.flush()
    for f in fields:
        db_session.add(
            DataSourceFieldProfile(
                data_source_id=data_source_id,
                profile_id=profile.id,
                field_name=f["field_name"],
                distinct_count=f.get("distinct_count"),
                sample_values=f.get("sample_values"),
                min_value=f.get("min_value"),
                max_value=f.get("max_value"),
            )
        )
    await db_session.commit()


async def test_profile_summary_reports_row_count_date_range_and_categorical_values(
    db_session,
) -> None:
    """The exact "it_backup_jobs_CSV" scenario from the bug report: a text
    Date column and a low-cardinality System column must ground the model in
    real numbers, not invented ones."""
    source = _source(
        1,
        "it_backup_jobs_CSV",
        [("Date", "string"), ("System", "string"), ("Result", "string")],
    )
    await _seed_profile(
        db_session,
        data_source_id=1,
        row_count=40,
        fields=[
            {
                "field_name": "Date",
                "distinct_count": 12,
                "min_value": "2026-06-13",
                "max_value": "2026-06-24",
            },
            {
                "field_name": "System",
                "distinct_count": 4,
                "sample_values": ["ERP", "FileServer", "MES", "PLM"],
            },
            {
                "field_name": "Result",
                "distinct_count": 2,
                "sample_values": ["Success", "Failed"],
            },
        ],
    )

    profiles = await profile_sources(db_session, [source])

    summary = profiles["it_backup_jobs_CSV"]
    assert "40 rows" in summary
    # The declared Teiid type is "string" (text-backed), not "date" -- the
    # summary must say "text" so the SQL generator knows to PARSETIMESTAMP it
    # rather than assume FORMATDATE works directly.
    assert '"Date" range 2026-06-13 to 2026-06-24 (text)' in summary
    assert "ERP" in summary and "FileServer" in summary
    assert "Success" in summary and "Failed" in summary


async def test_declared_date_type_used_over_content_sniffed_type(db_session) -> None:
    """A column Teiid actually stores as `date` must be labeled "date", not
    "text" -- the label drives which SQL date function the model reaches for."""
    source = _source(2, "orders_db", [("OrderDate", "date"), ("Region", "string")])
    await _seed_profile(
        db_session,
        data_source_id=2,
        row_count=500,
        fields=[
            {"field_name": "OrderDate", "min_value": "2026-01-01", "max_value": "2026-06-30"},
            {"field_name": "Region", "distinct_count": 3, "sample_values": ["East", "West", "Central"]},
        ],
    )

    profiles = await profile_sources(db_session, [source])

    assert '"OrderDate" range 2026-01-01 to 2026-06-30 (date)' in profiles["orders_db"]


async def test_high_cardinality_column_is_not_listed_as_categorical(db_session) -> None:
    """A column with more distinct values than the cap (e.g. a free-text
    field) must be omitted rather than shown as a misleadingly partial list."""
    source = _source(3, "tickets_CSV", [("CreatedDate", "string"), ("Description", "string")])
    await _seed_profile(
        db_session,
        data_source_id=3,
        row_count=5000,
        fields=[
            {"field_name": "CreatedDate", "min_value": "2026-01-01", "max_value": "2026-06-01"},
            {
                "field_name": "Description",
                "distinct_count": 4800,
                "sample_values": ["a", "b", "c", "d", "e"],
            },
        ],
    )

    profiles = await profile_sources(db_session, [source])

    assert "Description" not in profiles["tickets_CSV"]


async def test_source_with_no_persisted_profile_is_simply_omitted(db_session) -> None:
    """A source that predates upload-time profiling (or wasn't profiled) must
    not appear in the result -- profiling can only add grounding, never fail
    catalog building for that source."""
    source = _source(4, "legacy_CSV", [("Col", "string")])

    profiles = await profile_sources(db_session, [source])

    assert "legacy_CSV" not in profiles


async def test_empty_source_list_returns_empty_without_querying(db_session) -> None:
    assert await profile_sources(db_session, []) == {}
