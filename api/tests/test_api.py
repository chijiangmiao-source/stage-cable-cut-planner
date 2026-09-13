def valid_payload(**overrides):
    payload = {
        "roll_length": 1000,
        "kerf_width": 10,
        "segments": [
            {"id": "A", "length": 600},
            {"id": "B", "length": 590},
            {"id": "C", "length": 400},
        ],
    }
    payload.update(overrides)
    return payload


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_plan_persists_and_computes(client):
    resp = client.post("/api/plans", json=valid_payload())
    assert resp.status_code == 201
    plan = resp.json()
    # A: 600 alone (600+590+10 > 1000, 600+400+10 > 1000); B+C: 990+10 = 1000.
    assert plan["rolls_used"] == 2
    assert [r["position"] for r in plan["rolls"]] == [1, 2]
    assert [[s["id"] for s in r["segments"]] for r in plan["rolls"]] == [["A"], ["B", "C"]]
    assert [r["kerf_count"] for r in plan["rolls"]] == [0, 1]
    assert [r["leftover"] for r in plan["rolls"]] == [400, 0]
    assert plan["total_leftover"] == 400
    assert plan["total_kerf_count"] == 1

    # persisted and retrievable
    detail = client.get(f"/api/plans/{plan['id']}")
    assert detail.status_code == 200
    assert detail.json() == plan

    listing = client.get("/api/plans")
    assert listing.status_code == 200
    assert [p["id"] for p in listing.json()] == [plan["id"]]
    assert listing.json()[0]["segment_count"] == 3


def test_invalid_roll_length_rejected(client):
    resp = client.post("/api/plans", json=valid_payload(roll_length=0))
    assert resp.status_code == 422
    locs = [e["loc"] for e in resp.json()["detail"]]
    assert ["body", "roll_length"] in locs

    resp = client.post("/api/plans", json=valid_payload(roll_length=100001))
    assert resp.status_code == 422

    resp = client.post("/api/plans", json=valid_payload(kerf_width=0))
    assert resp.status_code == 422


def test_invalid_segment_length_rejected(client):
    payload = valid_payload()
    payload["segments"][1]["length"] = 0
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 422
    assert ["body", "segments", 1, "length"] in [
        e["loc"] for e in resp.json()["detail"]
    ]


def test_duplicate_ids_located_and_not_persisted(client):
    payload = valid_payload()
    payload["segments"][2]["id"] = "A"
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any(e["loc"] == ["segments", 2, "id"] for e in detail)
    assert client.get("/api/plans").json() == []


def test_segment_exceeding_roll_located_and_not_persisted(client):
    payload = valid_payload(roll_length=500)
    # A=600 and B=590 both exceed 500; C=400 fits.
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 422
    locs = [e["loc"] for e in resp.json()["detail"]]
    assert ["segments", 0, "length"] in locs
    assert ["segments", 1, "length"] in locs
    assert ["segments", 2, "length"] not in locs
    assert client.get("/api/plans").json() == []


def test_too_many_segments_rejected(client):
    payload = valid_payload()
    payload["segments"] = [
        {"id": f"S{i}", "length": 10} for i in range(13)
    ]
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 422


def test_missing_plan_404(client):
    assert client.get("/api/plans/999").status_code == 404


def test_ordinary_create_has_null_source_and_unchanged_semantics(client):
    resp = client.post("/api/plans", json=valid_payload())
    assert resp.status_code == 201
    plan = resp.json()
    # no source carried: ordinary creation, provenance stays null
    assert plan["source_plan_id"] is None

    detail = client.get(f"/api/plans/{plan['id']}").json()
    assert detail["source_plan_id"] is None
    assert detail == plan

    summary = client.get("/api/plans").json()[0]
    assert summary["source_plan_id"] is None
    assert "rolls" not in summary


def test_adjustment_carries_source_link_without_changing_solution(client):
    # original plan
    original = client.post("/api/plans", json=valid_payload()).json()

    # start an adjustment from the original: identical inputs, plus the link
    payload = valid_payload()
    payload["source_plan_id"] = original["id"]
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 201
    adjusted = resp.json()
    assert adjusted["id"] != original["id"]
    assert adjusted["source_plan_id"] == original["id"]

    # the solver consumes the edited inputs only: identical inputs must
    # produce identical rolls/kerfs/leftovers; provenance has no effect
    for key in (
        "roll_length",
        "kerf_width",
        "rolls_used",
        "total_kerf_count",
        "total_leftover",
        "rolls",
    ):
        assert adjusted[key] == original[key], key

    # both plans remain independently retrievable; the original stays
    # read-only and never points back at the adjustment
    original_detail = client.get(f"/api/plans/{original['id']}").json()
    assert original_detail["source_plan_id"] is None
    adjusted_detail = client.get(f"/api/plans/{adjusted['id']}").json()
    assert adjusted_detail["source_plan_id"] == original["id"]

    # the list summary carries provenance for the new plan only
    by_id = {p["id"]: p for p in client.get("/api/plans").json()}
    assert by_id[original["id"]]["source_plan_id"] is None
    assert by_id[adjusted["id"]]["source_plan_id"] == original["id"]


def test_edited_segment_recomputes_under_existing_rules(client):
    original = client.post("/api/plans", json=valid_payload()).json()
    assert original["rolls_used"] == 2  # [A], [B,C]
    assert [r["leftover"] for r in original["rolls"]] == [400, 0]

    # change one segment length: B 590 -> 380. The adjustment is re-solved
    # from the edited inputs; roll 2 recomputes to 380+400+10 = 790 (left 210).
    payload = valid_payload()
    payload["segments"][1]["length"] = 380
    payload["source_plan_id"] = original["id"]
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 201
    adjusted = resp.json()
    assert adjusted["source_plan_id"] == original["id"]
    assert adjusted["rolls_used"] == 2
    assert [[s["id"] for s in r["segments"]] for r in adjusted["rolls"]] == [
        ["A"],
        ["B", "C"],
    ]
    assert [r["leftover"] for r in adjusted["rolls"]] == [400, 210]
    assert adjusted["total_leftover"] == 610

    # the original plan stays as it was — provenance never mutates it
    original_detail = client.get(f"/api/plans/{original['id']}").json()
    assert [r["leftover"] for r in original_detail["rolls"]] == [400, 0]
    assert original_detail["total_leftover"] == 400


def test_invalid_source_rejected_with_located_error_and_not_persisted(client):
    payload = valid_payload()
    payload["source_plan_id"] = 999
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any(e["loc"] == ["source_plan_id"] for e in detail)
    # no orphan link and no half-finished record
    assert client.get("/api/plans").json() == []


def test_invalid_source_and_invalid_segment_both_reported(client):
    # Endpoint-level checks are accumulated in one pass: a missing source and
    # a segment longer than the roll are reported together.
    payload = valid_payload(roll_length=500)
    payload["source_plan_id"] = 4242
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 422
    locs = [e["loc"] for e in resp.json()["detail"]]
    assert ["source_plan_id"] in locs
    assert ["segments", 0, "length"] in locs
    assert client.get("/api/plans").json() == []


def test_non_positive_source_rejected_by_schema(client):
    payload = valid_payload()
    payload["source_plan_id"] = 0
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 422
    assert client.get("/api/plans").json() == []


# ---------------------------------------------------------------------------
# Numeric inputs must be genuine JSON integers. Booleans (a subclass of int
# in Python), quoted numbers and floats must never be coerced into
# millimetres or plan ids.
# ---------------------------------------------------------------------------


def test_boolean_measurements_rejected_not_treated_as_one_millimetre(client):
    # bool previously coerced to 1, producing a "one millimetre" plan.
    for field in ("roll_length", "kerf_width"):
        resp = client.post("/api/plans", json=valid_payload(**{field: True}))
        assert resp.status_code == 422, field
        locs = [tuple(e["loc"]) for e in resp.json()["detail"]]
        assert ("body", field) in locs, (field, locs)
        assert client.get("/api/plans").json() == []

    for field in ("length", "allowance"):
        payload = valid_payload()
        payload["segments"][0][field] = True
        resp = client.post("/api/plans", json=payload)
        assert resp.status_code == 422, field
        locs = [tuple(e["loc"]) for e in resp.json()["detail"]]
        assert ("body", "segments", 0, field) in locs, (field, locs)
        assert client.get("/api/plans").json() == []


def test_string_measurements_rejected_even_when_numeric(client):
    # Quoted numbers previously parsed into integers and saved.
    for field, value in (("roll_length", "1000"), ("kerf_width", "10")):
        resp = client.post("/api/plans", json=valid_payload(**{field: value}))
        assert resp.status_code == 422, field
        locs = [tuple(e["loc"]) for e in resp.json()["detail"]]
        assert ("body", field) in locs, (field, locs)

    for field, value in (("length", "600"), ("allowance", "0")):
        payload = valid_payload()
        payload["segments"][0][field] = value
        resp = client.post("/api/plans", json=payload)
        assert resp.status_code == 422, field
        locs = [tuple(e["loc"]) for e in resp.json()["detail"]]
        assert ("body", "segments", 0, field) in locs, (field, locs)

    assert client.get("/api/plans").json() == []


def test_float_measurements_rejected_including_integral_values(client):
    # 10.0 previously silently truncated to 10; non-integral floats too.
    for field, value in (("roll_length", 1000.0), ("kerf_width", 10.5)):
        resp = client.post("/api/plans", json=valid_payload(**{field: value}))
        assert resp.status_code == 422, field
        locs = [tuple(e["loc"]) for e in resp.json()["detail"]]
        assert ("body", field) in locs, (field, locs)

    for field, value in (("length", 600.0), ("allowance", 2.5)):
        payload = valid_payload()
        payload["segments"][0][field] = value
        resp = client.post("/api/plans", json=payload)
        assert resp.status_code == 422, field
        locs = [tuple(e["loc"]) for e in resp.json()["detail"]]
        assert ("body", "segments", 0, field) in locs, (field, locs)

    assert client.get("/api/plans").json() == []


def test_boolean_source_plan_id_rejected_and_never_links_to_plan_one(client):
    # Plan 1 exists; a bare `true` must not alias it as the source.
    original = client.post("/api/plans", json=valid_payload())
    assert original.status_code == 201
    assert original.json()["id"] == 1

    payload = valid_payload()
    payload["source_plan_id"] = True
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 422
    locs = [tuple(e["loc"]) for e in resp.json()["detail"]]
    assert ("body", "source_plan_id") in locs, locs

    # nothing was created and no provenance relationship exists
    plans = client.get("/api/plans").json()
    assert len(plans) == 1
    assert plans[0]["id"] == 1
    assert plans[0]["source_plan_id"] is None


def test_genuine_integer_measurements_still_create(client):
    # The strict check only narrows types; well-formed integer JSON is
    # unaffected, including an explicit integer source id.
    original = client.post("/api/plans", json=valid_payload()).json()
    payload = valid_payload()
    payload["source_plan_id"] = original["id"]
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 201
    assert resp.json()["source_plan_id"] == original["id"]


def test_chains_of_adjustments_keep_direct_source(client):
    first = client.post("/api/plans", json=valid_payload()).json()
    second_payload = valid_payload()
    second_payload["source_plan_id"] = first["id"]
    second = client.post("/api/plans", json=second_payload).json()

    third_payload = valid_payload()
    third_payload["source_plan_id"] = second["id"]
    third = client.post("/api/plans", json=third_payload).json()

    # only the directly named source is stored (no derived semantics)
    assert second["source_plan_id"] == first["id"]
    assert third["source_plan_id"] == second["id"]
    assert client.get(f"/api/plans/{first['id']}").json()["source_plan_id"] is None
# ---------------------------------------------------------------------------
# End-trim allowance (端头加工余量)
# ---------------------------------------------------------------------------


def test_allowance_omitted_matches_legacy_behavior(client):
    # Old clients send no allowance: the plan must be identical to the
    # pre-allowance behavior, with allowance reported as 0.
    resp = client.post("/api/plans", json=valid_payload())
    assert resp.status_code == 201
    plan = resp.json()
    assert plan["rolls_used"] == 2
    assert [[s["id"] for s in r["segments"]] for r in plan["rolls"]] == [
        ["A"],
        ["B", "C"],
    ]
    assert [r["leftover"] for r in plan["rolls"]] == [400, 0]
    assert all(
        s["allowance"] == 0 for r in plan["rolls"] for s in r["segments"]
    )

    # Explicit zeros must produce exactly the same plan.
    payload = valid_payload()
    for seg in payload["segments"]:
        seg["allowance"] = 0
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 201
    again = resp.json()
    assert [[s["id"] for s in r["segments"]] for r in again["rolls"]] == [
        ["A"],
        ["B", "C"],
    ]
    assert again["total_leftover"] == plan["total_leftover"]


def test_allowance_changes_packing_and_detail_closes(client):
    # C's allowance pushes its cut length to 450, so B+C (590+450+10) no
    # longer fits one roll: the packing changes from 2 rolls to 3.
    payload = valid_payload()
    payload["segments"][2]["allowance"] = 50
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 201
    plan = resp.json()
    assert plan["rolls_used"] == 3
    assert [[s["id"] for s in r["segments"]] for r in plan["rolls"]] == [
        ["A"],
        ["B"],
        ["C"],
    ]
    # Roll math closes on cut lengths: sum(length+allowance) + kerfs + leftover
    # == roll_length for every roll.
    for roll in plan["rolls"]:
        cut_sum = sum(s["length"] + s["allowance"] for s in roll["segments"])
        assert roll["used_length"] == cut_sum + roll["kerf_count"] * plan["kerf_width"]
        assert roll["used_length"] + roll["leftover"] == plan["roll_length"]
    assert [r["leftover"] for r in plan["rolls"]] == [400, 410, 550]
    assert plan["total_leftover"] == 1360
    # The allowance is persisted and returned by the detail endpoint.
    assert plan["rolls"][2]["segments"][0]["allowance"] == 50

    detail = client.get(f"/api/plans/{plan['id']}")
    assert detail.status_code == 200
    assert detail.json() == plan


def test_allowance_out_of_range_rejected_and_not_persisted(client):
    for bad in (-1, 10001):
        payload = valid_payload()
        payload["segments"][1]["allowance"] = bad
        resp = client.post("/api/plans", json=payload)
        assert resp.status_code == 422
        locs = [e["loc"] for e in resp.json()["detail"]]
        assert ["body", "segments", 1, "allowance"] in locs
    assert client.get("/api/plans").json() == []


def test_length_plus_allowance_exceeding_roll_located_at_allowance(client):
    payload = valid_payload(roll_length=500)
    payload["segments"] = [
        {"id": "A", "length": 400, "allowance": 150},  # 550 > 500: allowance's fault
        {"id": "B", "length": 600, "allowance": 10},  # 600 > 500: length's fault
        {"id": "C", "length": 450, "allowance": 50},  # 500 <= 500: fits exactly
    ]
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 422
    locs = [e["loc"] for e in resp.json()["detail"]]
    assert ["segments", 0, "allowance"] in locs
    assert ["segments", 1, "length"] in locs
    # C fits, so no error points at it at all.
    assert all(loc[1] != 2 for loc in locs if len(loc) == 3)
    assert client.get("/api/plans").json() == []


# ---------------------------------------------------------------------------
# Segment kits (套组): members stay on one roll.
# ---------------------------------------------------------------------------


def _rolls_of(plan):
    return [[s["id"] for s in r["segments"]] for r in plan["rolls"]]


def test_request_without_kit_field_matches_legacy_plan(client):
    # valid_payload() carries no kit_id anywhere; the solution must be
    # identical to the old behavior and every cut reports kit_id None.
    resp = client.post("/api/plans", json=valid_payload())
    assert resp.status_code == 201
    plan = resp.json()
    assert _rolls_of(plan) == [["A"], ["B", "C"]]
    assert all(
        s["kit_id"] is None
        for r in plan["rolls"] for s in r["segments"]
    )
    # historical-shaped response on refetch stays null and equal
    assert client.get(f"/api/plans/{plan['id']}").json() == plan


def test_explicit_null_and_empty_kit_ids_are_independent(client):
    for value in (None, ""):
        payload = valid_payload()
        for seg in payload["segments"]:
            seg["kit_id"] = value
        resp = client.post("/api/plans", json=payload)
        assert resp.status_code == 201, resp.json()
        assert _rolls_of(resp.json()) == [["A"], ["B", "C"]]
        assert all(
            s["kit_id"] is None
            for r in resp.json()["rolls"] for s in r["segments"]
        )


def test_fittable_kit_never_spans_rolls_and_capacity_closes(client):
    # Independent optimum: A=400 alone, B=400 + C=300 share roll 2.
    # Kit {A,B} forces both onto one roll: [A,B]=810, C alone.
    payload = {
        "roll_length": 1000,
        "kerf_width": 10,
        "segments": [
            {"id": "A", "length": 400, "kit_id": "SET1"},
            {"id": "B", "length": 400, "kit_id": "SET1"},
            {"id": "C", "length": 300},
        ],
    }
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 201, resp.json()
    plan = resp.json()
    assert plan["rolls_used"] == 2
    assert _rolls_of(plan) == [["A", "B"], ["C"]]
    assert [[s["kit_id"] for s in r["segments"]] for r in plan["rolls"]] == [
        ["SET1", "SET1"],
        [None],
    ]
    # every roll still recomputes from cut lengths + kerfs
    for roll in plan["rolls"]:
        cut_sum = sum(s["length"] + s["allowance"] for s in roll["segments"])
        assert roll["used_length"] == cut_sum + plan["kerf_width"] * roll["kerf_count"]
        assert roll["used_length"] + roll["leftover"] == plan["roll_length"]
    assert [r["leftover"] for r in plan["rolls"]] == [190, 700]

    # persisted markers survive the detail refetch
    detail = client.get(f"/api/plans/{plan['id']}")
    assert detail.status_code == 200
    assert detail.json() == plan


def test_kit_counts_allowance_and_internal_kerfs(client):
    # Cut lengths 460 (A) + 500 (C) + 10 kerf = 970 fit together; without the
    # kit the independent optimum is [A],[B,C]. The kit pulls A and C together.
    payload = {
        "roll_length": 1000,
        "kerf_width": 10,
        "segments": [
            {"id": "A", "length": 400, "allowance": 60, "kit_id": "G1"},
            {"id": "B", "length": 400},
            {"id": "C", "length": 500, "kit_id": "G1"},
        ],
    }
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 201, resp.json()
    plan = resp.json()
    assert _rolls_of(plan) == [["A", "C"], ["B"]]
    first = plan["rolls"][0]
    assert first["used_length"] == 460 + 500 + 10
    assert first["leftover"] == 30


def test_kit_with_minimum_roll_count_takes_precedence_over_lex_order(client):
    # [A,B,C] fits one roll; the canonical one-roll solution is produced even
    # though the first lex candidate (A alone) would split the {A,C} kit and
    # force an infeasible remainder.
    payload = {
        "roll_length": 1000,
        "kerf_width": 10,
        "segments": [
            {"id": "A", "length": 300, "kit_id": "K"},
            {"id": "B", "length": 300},
            {"id": "C", "length": 300, "kit_id": "K"},
        ],
    }
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 201
    assert _rolls_of(resp.json()) == [["A", "B", "C"]]
    assert resp.json()["rolls_used"] == 1


def test_unfittable_kit_returns_located_errors_and_persists_nothing(client):
    # A=600, C=400 in one kit: 600+400+10 = 1010 > 1000 (10 mm over).
    payload = {
        "roll_length": 1000,
        "kerf_width": 10,
        "segments": [
            {"id": "A", "length": 600, "kit_id": "BIG"},
            {"id": "B", "length": 100},
            {"id": "C", "length": 400, "kit_id": "BIG"},
        ],
    }
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    # the error lands on the kit input of each member, stating the overflow
    assert {tuple(e["loc"]) for e in detail} == {
        ("segments", 0, "kit_id"),
        ("segments", 2, "kit_id"),
    }
    for e in detail:
        assert "BIG" in e["msg"]
        assert "1010" in e["msg"]  # required length incl. internal kerfs
        assert "10 mm" in e["msg"]  # overflow in millimetres
    # the independent segment B has no kit error
    assert all(e["loc"][1] != 1 for e in detail)
    # failed submission produces no plan
    assert client.get("/api/plans").json() == []


def test_unfittable_kit_overflow_includes_member_allowances(client):
    payload = {
        "roll_length": 500,
        "kerf_width": 10,
        "segments": [
            {"id": "A", "length": 300, "kit_id": "G"},
            {"id": "B", "length": 150, "allowance": 50, "kit_id": "G"},
        ],
    }
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 422
    locs = [tuple(e["loc"]) for e in resp.json()["detail"]]
    assert locs == [("segments", 0, "kit_id"), ("segments", 1, "kit_id")]
    msg = resp.json()["detail"][0]["msg"]
    # 300 + 200 + 10 = 510, 10 mm beyond the roll
    assert "510" in msg and "10 mm" in msg
    assert client.get("/api/plans").json() == []


def test_kit_error_accumulates_with_other_field_errors(client):
    # oversized independent segment + unfittable kit reported in one response
    payload = {
        "roll_length": 500,
        "kerf_width": 10,
        "segments": [
            {"id": "A", "length": 300, "kit_id": "G"},
            {"id": "B", "length": 250, "kit_id": "G"},  # 300+250+10 = 560 > 500
            {"id": "C", "length": 600},  # 600 > 500
        ],
    }
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 422
    locs = {tuple(e["loc"]) for e in resp.json()["detail"]}
    assert ("segments", 0, "kit_id") in locs
    assert ("segments", 1, "kit_id") in locs
    assert ("segments", 2, "length") in locs
    assert client.get("/api/plans").json() == []


def test_oversized_kit_member_is_blamed_on_length_not_kit(client):
    payload = {
        "roll_length": 500,
        "kerf_width": 10,
        "segments": [
            {"id": "A", "length": 600, "kit_id": "G"},  # member exceeds the roll
            {"id": "B", "length": 100, "kit_id": "G"},
        ],
    }
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 422
    locs = {tuple(e["loc"]) for e in resp.json()["detail"]}
    assert ("segments", 0, "length") in locs
    # the member-level fault owns the rejection; no kit overflow is reported
    assert not any(loc[-1] == "kit_id" for loc in locs)
    assert client.get("/api/plans").json() == []

    # same when the allowance (not the delivered length) pushes the member over
    payload["segments"][0] = {"id": "A", "length": 400, "allowance": 200, "kit_id": "G"}
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 422
    locs = {tuple(e["loc"]) for e in resp.json()["detail"]}
    assert ("segments", 0, "allowance") in locs
    assert not any(loc[-1] == "kit_id" for loc in locs)


def test_invalid_kit_id_shape_rejected_at_field(client):
    payload = valid_payload()
    payload["segments"][0]["kit_id"] = "-bad-"  # must start alphanumerically
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 422
    locs = [tuple(e["loc"]) for e in resp.json()["detail"]]
    assert ("body", "segments", 0, "kit_id") in locs
    assert client.get("/api/plans").json() == []


def test_kit_marker_does_not_change_adjustment_link(client):
    original = client.post("/api/plans", json=valid_payload()).json()
    payload = {
        "roll_length": 1000,
        "kerf_width": 10,
        "source_plan_id": original["id"],
        "segments": [
            {"id": "A", "length": 400, "kit_id": "SET1"},
            {"id": "B", "length": 400, "kit_id": "SET1"},
            {"id": "C", "length": 300},
        ],
    }
    resp = client.post("/api/plans", json=payload)
    assert resp.status_code == 201
    adjusted = resp.json()
    assert adjusted["source_plan_id"] == original["id"]
    assert _rolls_of(adjusted) == [["A", "B"], ["C"]]
    assert all(
        s["kit_id"] == "SET1"
        for s in adjusted["rolls"][0]["segments"]
    )
