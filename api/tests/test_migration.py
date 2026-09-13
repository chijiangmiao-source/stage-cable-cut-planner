"""The provenance column must be addable to a database created by an older
release: existing plans keep working and their source stays NULL.
"""

import os

# Must be set before any app module is imported so the engine picks it up.
os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from sqlalchemy import inspect, text

from app.db import Base, engine, run_migrations


# Legacy DDL, exactly as the previous release created the plans table.
LEGACY_PLANS_DDL = """
CREATE TABLE plans (
    id INTEGER NOT NULL PRIMARY KEY,
    roll_length INTEGER NOT NULL,
    kerf_width INTEGER NOT NULL,
    segment_count INTEGER NOT NULL,
    rolls_used INTEGER NOT NULL,
    total_kerf_count INTEGER NOT NULL,
    total_leftover INTEGER NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


@pytest.fixture
def legacy_db():
    # Build a database containing only the old-schema plans table.
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text(LEGACY_PLANS_DDL))
    yield
    Base.metadata.drop_all(bind=engine)


def test_migration_adds_nullable_source_to_legacy_schema(legacy_db):
    cols = {c["name"] for c in inspect(engine).get_columns("plans")}
    assert "source_plan_id" not in cols

    # Seed a legacy row directly (NOT NULL columns only, as the old app did).
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO plans (roll_length, kerf_width, segment_count, "
                "rolls_used, total_kerf_count, total_leftover, created_at) "
                "VALUES (1000, 10, 3, 2, 1, 400, '2026-09-01 00:00:00+00')"
            )
        )

    # Startup upgrade path; running it twice must be a no-op.
    run_migrations()
    run_migrations()

    cols = {c["name"] for c in inspect(engine).get_columns("plans")}
    assert "source_plan_id" in cols

    # Every pre-existing plan has an empty provenance link...
    with engine.begin() as conn:
        row = conn.execute(text("SELECT id, source_plan_id FROM plans")).first()
    assert row is not None
    assert row.source_plan_id is None

    # ...and normal access patterns (list/detail) are unaffected.
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        listing = client.get("/api/plans").json()
        assert [p["id"] for p in listing] == [row.id]
        assert listing[0]["source_plan_id"] is None
        detail = client.get(f"/api/plans/{row.id}")
        assert detail.status_code == 200
        assert detail.json()["source_plan_id"] is None


def test_compat_migration_adds_nullable_kit_id_to_legacy_cuts():
    # A database whose cuts table predates both allowance and kit columns
    # (as create_all-era deployments had) gains the nullable kit marker;
    # historical cuts report kit_id None and keep their packing semantics.
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text(LEGACY_PLANS_DDL))
        conn.execute(
            text(
                "CREATE TABLE rolls (id INTEGER NOT NULL PRIMARY KEY, "
                "plan_id INTEGER NOT NULL, position INTEGER NOT NULL, "
                "kerf_count INTEGER NOT NULL, used_length INTEGER NOT NULL, "
                "leftover INTEGER NOT NULL)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE cuts (id INTEGER NOT NULL PRIMARY KEY, "
                "roll_id INTEGER NOT NULL, position INTEGER NOT NULL, "
                "segment_id VARCHAR(32) NOT NULL, length INTEGER NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO plans (roll_length, kerf_width, segment_count, "
                "rolls_used, total_kerf_count, total_leftover, created_at) "
                "VALUES (1000, 10, 1, 1, 0, 900, '2026-09-01 00:00:00+00')"
            )
        )
        conn.execute(text("INSERT INTO rolls VALUES (1, 1, 1, 0, 100, 900)"))
        conn.execute(text("INSERT INTO cuts VALUES (1, 1, 1, 'A', 100)"))

    run_migrations()
    run_migrations()  # idempotent

    cols = {c["name"] for c in inspect(engine).get_columns("cuts")}
    assert "kit_id" in cols
    assert "allowance" in cols
    with engine.begin() as conn:
        row = conn.execute(text("SELECT allowance, kit_id FROM cuts")).first()
    assert row.allowance == 0
    assert row.kit_id is None

    Base.metadata.drop_all(bind=engine)
