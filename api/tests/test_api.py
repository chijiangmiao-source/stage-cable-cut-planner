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
