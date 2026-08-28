"""Tests for the AST-based SQL authorization gate (TS-ISO-002).

Run from ``platform-api``: ``pytest -q tests/test_sql_authorization.py``.
"""

from __future__ import annotations

import pytest

from app.services.sql_authorization import SQLAuthorizationError, authorize_sql

ALLOWED = ["it_backup_jobs_CSV", "sales_revenue_CSV"]


def test_accepts_plain_select():
    authorize_sql('SELECT "Status" FROM "it_backup_jobs_CSV"', ALLOWED)


def test_accepts_cte_select():
    authorize_sql(
        'WITH x AS (SELECT "Status" FROM "it_backup_jobs_CSV") SELECT * FROM x',
        ALLOWED,
    )


def test_accepts_union_of_selects():
    authorize_sql(
        'SELECT "Status" FROM "it_backup_jobs_CSV" '
        'UNION SELECT "Status" FROM "it_backup_jobs_CSV"',
        ALLOWED,
    )


@pytest.mark.parametrize(
    "sql",
    [
        'INSERT INTO "it_backup_jobs_CSV" ("Status") VALUES (\'x\')',
        'UPDATE "it_backup_jobs_CSV" SET "Status" = \'x\'',
        'DELETE FROM "it_backup_jobs_CSV"',
        'MERGE INTO "it_backup_jobs_CSV" USING "sales_revenue_CSV" ON true '
        "WHEN MATCHED THEN DELETE",
        'DROP TABLE "it_backup_jobs_CSV"',
        'CREATE TABLE evil (id int)',
        'ALTER TABLE "it_backup_jobs_CSV" ADD COLUMN evil int',
        "CALL some_procedure()",
        "TRUNCATE TABLE \"it_backup_jobs_CSV\"",
        "BEGIN",
    ],
)
def test_rejects_write_ddl_and_procedural_statements(sql):
    with pytest.raises(SQLAuthorizationError):
        authorize_sql(sql, ALLOWED)


def test_rejects_stacked_statements():
    with pytest.raises(SQLAuthorizationError, match="single SQL statement"):
        authorize_sql(
            'SELECT "Status" FROM "it_backup_jobs_CSV"; '
            'DROP TABLE "it_backup_jobs_CSV"',
            ALLOWED,
        )


def test_rejects_dml_hidden_in_a_cte():
    sql = (
        'WITH x AS (INSERT INTO "it_backup_jobs_CSV" ("Status") VALUES (\'x\') '
        "RETURNING *) SELECT * FROM x"
    )
    with pytest.raises(SQLAuthorizationError, match="Disallowed SQL construct"):
        authorize_sql(sql, ALLOWED)


def test_rejects_dml_hidden_in_a_union_branch():
    sql = (
        'SELECT "Status" FROM "it_backup_jobs_CSV" '
        "UNION ALL SELECT * FROM (DELETE FROM \"it_backup_jobs_CSV\" RETURNING *) t"
    )
    with pytest.raises(SQLAuthorizationError):
        authorize_sql(sql, ALLOWED)


def test_comment_does_not_hide_a_second_statement():
    sql = 'SELECT "Status" FROM "it_backup_jobs_CSV" -- innocuous\n; DROP TABLE "it_backup_jobs_CSV"'
    with pytest.raises(SQLAuthorizationError):
        authorize_sql(sql, ALLOWED)


def test_rejects_unauthorized_table_reference():
    with pytest.raises(SQLAuthorizationError, match="Unauthorized table reference"):
        authorize_sql('SELECT * FROM "some_other_project_table"', ALLOWED)


def test_rejects_unauthorized_table_in_a_join():
    with pytest.raises(SQLAuthorizationError, match="Unauthorized table reference"):
        authorize_sql(
            'SELECT a."Status" FROM "it_backup_jobs_CSV" a '
            'JOIN "some_other_project_table" b ON a."Id" = b."Id"',
            ALLOWED,
        )


def test_allows_any_table_when_allowed_tables_is_empty():
    # Matches ai-server's validate_sql: an empty allowlist means the
    # table-reference check is off, not "nothing is allowed".
    authorize_sql('SELECT * FROM "anything"', [])


def test_rejects_empty_sql():
    with pytest.raises(SQLAuthorizationError):
        authorize_sql("", ALLOWED)


def test_rejects_unparseable_sql():
    with pytest.raises(SQLAuthorizationError):
        authorize_sql("this is not valid SQL at all @#$%", ALLOWED)


def test_table_name_matching_is_case_insensitive():
    authorize_sql('SELECT * FROM "IT_BACKUP_JOBS_CSV"', ALLOWED)
