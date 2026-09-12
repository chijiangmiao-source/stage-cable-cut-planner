"""One-shot acceptance checks against the running Docker Compose stack.

Exercises the real integration path: browser-facing nginx (web) -> FastAPI
(api) -> PostgreSQL. Exits 0 only if every check passes.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

API_URL = os.environ.get("API_URL", "http://api:8000").rstrip("/")
WEB_URL = os.environ.get("WEB_URL", "http://web:80").rstrip("/")

failures: list[str] = []


def _decode(raw):
    try:
        return json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return raw


def request(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, _decode(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, _decode(exc.read().decode())


def check(name, condition, detail=""):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}"
          + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(name)


def locs_of(body):
    if isinstance(body, dict):
        return [e.get("loc") for e in body.get("detail", []) if isinstance(e, dict)]
    return []


def wait_for(name, url, attempts=90):
    for _ in range(attempts):
        try:
            status, _ = request("GET", url)
            if status == 200:
                print(f"[ OK ] {name} healthy at {url}")
                return True
        except Exception:
            pass
        time.sleep(1)
    print(f"[FAIL] {name} never became healthy at {url}")
    return False


def main():
    ok = wait_for("api", f"{API_URL}/api/health")
    ok = wait_for("web", f"{WEB_URL}/") and ok
    if not ok:
        sys.exit(1)

    # --- invalid input: 422 with field locations, nothing persisted ---------
    dup = {
        "roll_length": 1000,
        "kerf_width": 10,
        "segments": [
            {"id": "A", "length": 100},
            {"id": "A", "length": 200},
        ],
    }
    status, body = request("POST", f"{WEB_URL}/api/plans", dup)
    check("duplicate id -> 422 via web proxy", status == 422, str(body))
    check("duplicate id error locates the segment",
          ["segments", 1, "id"] in locs_of(body), str(body))

    oversized = {
        "roll_length": 500,
        "kerf_width": 10,
        "segments": [{"id": "BIG", "length": 600}],
    }
    status, body = request("POST", f"{API_URL}/api/plans", oversized)
    check("oversized segment -> 422", status == 422, str(body))
    check("oversized error locates segment length",
          ["segments", 0, "length"] in locs_of(body), str(body))

    status, plans = request("GET", f"{API_URL}/api/plans")
    check("nothing persisted after invalid submissions",
          status == 200 and plans == [], str(plans))

    # --- kerf accounting: 50 + 50 + 30 kerf > 100 forces two rolls ----------
    case1 = {
        "roll_length": 100,
        "kerf_width": 30,
        "segments": [
            {"id": "X", "length": 50},
            {"id": "Y", "length": 50},
        ],
    }
    status, plan1 = request("POST", f"{WEB_URL}/api/plans", case1)
    check("kerf case created", status == 201 and isinstance(plan1, dict), str(plan1))
    if not isinstance(plan1, dict):
        sys.exit(1)
    check("kerf case uses 2 rolls", plan1.get("rolls_used") == 2, str(plan1))
    check("kerf case total leftover is 100",
          plan1.get("total_leftover") == 100, str(plan1))

    # --- canonical tie-break: [[A,B],[C,D]] ----------------------------------
    case2 = {
        "roll_length": 100,
        "kerf_width": 5,
        "segments": [{"id": c, "length": 40} for c in ("C", "A", "D", "B")],
    }
    status, plan2 = request("POST", f"{WEB_URL}/api/plans", case2)
    check("tie-break case created", status == 201 and isinstance(plan2, dict), str(plan2))
    if not isinstance(plan2, dict):
        sys.exit(1)
    got = [[s["id"] for s in r["segments"]] for r in plan2.get("rolls", [])]
    check("tie-break order is [[A,B],[C,D]]", got == [["A", "B"], ["C", "D"]], str(got))
    check("tie-break kerf counts are [1, 1]",
          [r["kerf_count"] for r in plan2.get("rolls", [])] == [1, 1])
    check("tie-break leftovers are [15, 15]",
          [r["leftover"] for r in plan2.get("rolls", [])] == [15, 15])

    # --- every roll recomputes by hand ---------------------------------------
    for roll in plan2.get("rolls", []):
        total = (sum(s["length"] for s in roll["segments"])
                 + roll["kerf_count"] * plan2["kerf_width"]
                 + roll["leftover"])
        check(f"roll {roll['position']} recomputes: segments + kerfs + leftover = roll length",
              total == plan2["roll_length"])

    # --- persistence: detail and list endpoints ------------------------------
    status, fetched = request("GET", f"{WEB_URL}/api/plans/{plan2['id']}")
    check("detail endpoint returns the persisted plan",
          status == 200 and fetched == plan2)

    status, plans = request("GET", f"{API_URL}/api/plans")
    ids = [p["id"] for p in plans] if status == 200 and isinstance(plans, list) else []
    check("plan list contains both created plans",
          plan1["id"] in ids and plan2["id"] in ids, str(ids))

    print()
    if failures:
        print(f"VERIFY FAILED: {len(failures)} check(s) failed")
        sys.exit(1)
    print("VERIFY PASSED: all acceptance checks succeeded")


if __name__ == "__main__":
    main()
