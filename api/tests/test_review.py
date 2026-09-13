"""Material review sheets (用料复核单): creation computes per-roll deviations
against the plan's stored leftovers and a whole-batch verdict; every invalid
submission is a located 422/409 that persists nothing and never rewrites the
plan, its cuts or the cutting progress.
"""

from sqlalchemy import create_engine, inspect, text

from app.migrations import run_startup_migrations


def make_plan(client):
    """roll 1 = [A] leftover 400; roll 2 = [B, C] leftover 0."""
    resp = client.post(
        "/api/plans",
        json={
            "roll_length": 1000,
            "kerf_width": 10,
            "segments": [
                {"id": "A", "length": 600},
                {"id": "B", "length": 590},
                {"id": "C", "length": 400},
            ],
        },
    )
    assert resp.status_code == 201
    return resp.json()


def complete_all(client, plan):
    for roll in plan["rolls"]:
        for position in range(1, len(roll["segments"]) + 1):
            resp = client.post(
                f"/api/plans/{plan['id']}/rolls/{roll['position']}/complete",
                json={"position": position},
            )
            assert resp.status_code == 200
    return client.get(f"/api/plans/{plan['id']}").json()


def create_sheet(client, plan_id, tolerance=20, measured=(380, 20)):
    return client.post(
        "/api/review-sheets",
        json={
            "plan_id": plan_id,
            "tolerance_mm": tolerance,
            "measurements": [
                {"roll_position": 1, "measured_leftover": measured[0]},
                {"roll_position": 2, "measured_leftover": measured[1]},
            ],
        },
    )


def locs_of(body):
    return [tuple(e["loc"]) for e in body.json()["detail"]]


def test_create_sheet_computes_deviations_and_verdicts(client):
    plan = complete_all(client, make_plan(client))
    before = client.get(f"/api/plans/{plan['id']}").json()

    # boundary deviations (exactly the tolerance) still pass
    resp = create_sheet(client, plan["id"], tolerance=20, measured=(380, 20))
    assert resp.status_code == 201
    sheet = resp.json()
    assert sheet["plan_id"] == plan["id"]
    assert sheet["tolerance_mm"] == 20
    assert sheet["batch_ok"] is True
    assert sheet["created_at"] is not None
    assert [
        (
            m["roll_position"],
            m["theoretical_leftover"],
            m["measured_leftover"],
            m["deviation"],
            m["ok"],
        )
        for m in sheet["measurements"]
    ] == [
        (1, 400, 380, 20, True),
        (2, 0, 20, 20, True),
    ]

    # persisted: both lookups return the identical sheet after a refetch
    fetched = client.get(f"/api/review-sheets/{sheet['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == sheet
    by_plan = client.get(f"/api/plans/{plan['id']}/review-sheet")
    assert by_plan.status_code == 200
    assert by_plan.json() == sheet

    # the plan, its cuts and the recorded progress are untouched
    assert client.get(f"/api/plans/{plan['id']}").json() == before


def test_over_tolerance_marks_roll_and_batch_abnormal(client):
    plan = make_plan(client)
    resp = create_sheet(client, plan["id"], tolerance=20, measured=(390, 100))
    assert resp.status_code == 201
    sheet = resp.json()
    assert [m["deviation"] for m in sheet["measurements"]] == [10, 100]
    assert [m["ok"] for m in sheet["measurements"]] == [True, False]
    assert sheet["batch_ok"] is False

    # the verdict survives a refetch unchanged
    assert client.get(f"/api/review-sheets/{sheet['id']}").json() == sheet


def test_duplicate_sheet_conflicts_and_changes_nothing(client):
    plan = make_plan(client)
    first = create_sheet(client, plan["id"])
    assert first.status_code == 201
    sheet = first.json()
    plan_before = client.get(f"/api/plans/{plan['id']}").json()

    resp = create_sheet(client, plan["id"], tolerance=5, measured=(1, 2))
    assert resp.status_code == 409

    # the original sheet and the plan are both unchanged
    assert client.get(f"/api/review-sheets/{sheet['id']}").json() == sheet
    assert client.get(f"/api/plans/{plan['id']}/review-sheet").json() == sheet
    assert client.get(f"/api/plans/{plan['id']}").json() == plan_before


def test_unknown_plan_is_located_422_and_persists_nothing(client):
    resp = create_sheet(client, 999999)
    assert resp.status_code == 422
    assert ("plan_id",) in locs_of(resp)
    assert client.get("/api/plans/999999/review-sheet").status_code == 404


def test_missing_roll_is_located_on_measurements(client):
    plan = make_plan(client)
    resp = client.post(
        "/api/review-sheets",
        json={
            "plan_id": plan["id"],
            "tolerance_mm": 20,
            "measurements": [{"roll_position": 1, "measured_leftover": 400}],
        },
    )
    assert resp.status_code == 422
    assert ("measurements",) in locs_of(resp)
    assert "2" in resp.json()["detail"][0]["msg"]
    assert client.get(f"/api/plans/{plan['id']}/review-sheet").status_code == 404


def test_duplicate_roll_position_is_located_on_the_row(client):
    plan = make_plan(client)
    resp = client.post(
        "/api/review-sheets",
        json={
            "plan_id": plan["id"],
            "tolerance_mm": 20,
            "measurements": [
                {"roll_position": 1, "measured_leftover": 400},
                {"roll_position": 1, "measured_leftover": 390},
            ],
        },
    )
    assert resp.status_code == 422
    assert ("measurements", 1, "roll_position") in locs_of(resp)
    assert client.get(f"/api/plans/{plan['id']}/review-sheet").status_code == 404


def test_roll_outside_plan_is_located_on_the_row(client):
    plan = make_plan(client)
    resp = client.post(
        "/api/review-sheets",
        json={
            "plan_id": plan["id"],
            "tolerance_mm": 20,
            "measurements": [
                {"roll_position": 1, "measured_leftover": 400},
                {"roll_position": 3, "measured_leftover": 0},
            ],
        },
    )
    assert resp.status_code == 422
    assert ("measurements", 1, "roll_position") in locs_of(resp)
    assert client.get(f"/api/plans/{plan['id']}/review-sheet").status_code == 404


def test_measured_value_type_and_range_errors_are_located(client):
    plan = make_plan(client)
    base = {
        "plan_id": plan["id"],
        "tolerance_mm": 20,
        "measurements": [
            {"roll_position": 1, "measured_leftover": 400},
            {"roll_position": 2, "measured_leftover": 0},
        ],
    }
    for bad in (True, "400", 400.0, -1, 100001):
        payload = dict(base)
        payload["measurements"] = [
            dict(base["measurements"][0]),
            {"roll_position": 2, "measured_leftover": bad},
        ]
        resp = client.post("/api/review-sheets", json=payload)
        assert resp.status_code == 422, bad
        locs = locs_of(resp)
        assert (
            ("measurements", 1, "measured_leftover") in locs
            or ("body", "measurements", 1, "measured_leftover") in locs
        ), (bad, locs)
    assert client.get(f"/api/plans/{plan['id']}/review-sheet").status_code == 404


def test_tolerance_type_and_range_errors_are_located(client):
    plan = make_plan(client)
    for bad in (True, "20", 20.0, -1, 10001):
        resp = client.post(
            "/api/review-sheets",
            json={
                "plan_id": plan["id"],
                "tolerance_mm": bad,
                "measurements": [
                    {"roll_position": 1, "measured_leftover": 400},
                    {"roll_position": 2, "measured_leftover": 0},
                ],
            },
        )
        assert resp.status_code == 422, bad
        locs = locs_of(resp)
        assert ("tolerance_mm",) in locs or ("body", "tolerance_mm") in locs, (
            bad,
            locs,
        )
    assert client.get(f"/api/plans/{plan['id']}/review-sheet").status_code == 404


def test_roll_position_type_errors_are_located(client):
    plan = make_plan(client)
    for bad in (True, "1", 1.0, 0):
        resp = client.post(
            "/api/review-sheets",
            json={
                "plan_id": plan["id"],
                "tolerance_mm": 20,
                "measurements": [
                    {"roll_position": bad, "measured_leftover": 400},
                    {"roll_position": 2, "measured_leftover": 0},
                ],
            },
        )
        assert resp.status_code == 422, bad
        locs = locs_of(resp)
        assert (
            ("measurements", 0, "roll_position") in locs
            or ("body", "measurements", 0, "roll_position") in locs
        ), (bad, locs)
    assert client.get(f"/api/plans/{plan['id']}/review-sheet").status_code == 404


def test_unknown_sheet_and_sheetless_plan_are_404(client):
    plan = make_plan(client)
    assert client.get("/api/review-sheets/999999").status_code == 404
    assert (
        client.get(f"/api/plans/{plan['id']}/review-sheet").status_code == 404
    )
    assert client.get("/api/plans/999999/review-sheet").status_code == 404


# --- migrations -------------------------------------------------------------


def test_legacy_database_at_kit_revision_gains_review_tables(tmp_path):
    # A database already stamped at 0003 (kit_id live, no review tables) is
    # upgraded in place: the new tables appear empty and the historical plan
    # stays directly accessible.
    db_path = tmp_path / "rev3.db"
    legacy = create_engine(f"sqlite:///{db_path}")
    with legacy.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE plans (id INTEGER PRIMARY KEY, "
                "roll_length INTEGER NOT NULL, kerf_width INTEGER NOT NULL, "
                "segment_count INTEGER NOT NULL, rolls_used INTEGER NOT NULL, "
                "total_kerf_count INTEGER NOT NULL, "
                "total_leftover INTEGER NOT NULL, "
                "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE rolls (id INTEGER PRIMARY KEY, "
                "plan_id INTEGER NOT NULL REFERENCES plans(id) "
                "ON DELETE CASCADE, position INTEGER NOT NULL, "
                "kerf_count INTEGER NOT NULL, used_length INTEGER NOT NULL, "
                "leftover INTEGER NOT NULL)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE cuts (id INTEGER PRIMARY KEY, "
                "roll_id INTEGER NOT NULL REFERENCES rolls(id) "
                "ON DELETE CASCADE, position INTEGER NOT NULL, "
                "segment_id VARCHAR(32) NOT NULL, length INTEGER NOT NULL, "
                "allowance INTEGER NOT NULL DEFAULT 0, "
                "kit_id VARCHAR(32), completed_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO alembic_version (version_num) VALUES "
                "('0003_cut_kit_id')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO plans VALUES (1, 1000, 10, 1, 1, 0, 900, "
                "'2026-01-01 00:00:00')"
            )
        )

    run_startup_migrations(legacy)

    tables = set(inspect(legacy).get_table_names())
    assert {"review_sheets", "review_measurements"} <= tables
    with legacy.connect() as conn:
        assert (
            conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            == "0004_review_sheets"
        )
        # historical plan row is untouched and has no sheet
        assert conn.execute(text("SELECT COUNT(*) FROM plans")).scalar() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM review_sheets")).scalar() == 0
