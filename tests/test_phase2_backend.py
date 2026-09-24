"""
Phase 2 backend acceptance test.

Usage (PowerShell):
    py tests\\test_phase2_backend.py
    $env:BASE = "http://localhost:8000"; py tests\\test_phase2_backend.py

Prints PASS/FAIL per check, client time, server time (X-Response-Time-ms) and Supabase calls (X-DB-Calls).
NOTE: resets the current trip of all 7 buses and inserts test tickets.
"""
import os
import sys
import time
import uuid
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = os.environ.get("BASE", "https://prototype2-qqw6.onrender.com").rstrip("/")
TIMEOUT = 90
VJA, TAD, MAN, NAM, PED, GNT = ("VIJAYAWADA PNBS", "TADEPALLI", "MANGALAGIRI", "NAMBURU",
                                "PEDDAKAKANI", "GUNTUR RTC")
BUSES = ["AP-16-1234", "AP-16-4023", "AP-16-4024", "AP-16-4025", "AP-16-4026", "AP-16-5001", "AP-16-5002"]
GNT_VJA = {"AP-16-5001", "AP-16-5002"}
MAIN = "AP-16-1234"

session = requests.Session()
results = []                      # (ok, label)
timings = defaultdict(list)       # endpoint -> [(client_s, server_ms, db_calls)]
lock = threading.Lock()


def call(method, path, sess=None, **kw):
    sess = sess or session
    t0 = time.perf_counter()
    r = sess.request(method, BASE + path, timeout=TIMEOUT, **kw)
    dt = time.perf_counter() - t0
    try:
        body = r.json()
    except ValueError:
        body = {"_raw": r.text[:200]}
    server_ms = int(r.headers.get("X-Response-Time-ms", "-1"))
    db_calls = int(r.headers.get("X-DB-Calls", "-1"))
    ep = "/" + "/".join(path.split("?")[0].strip("/").split("/")[:2])
    with lock:
        timings[ep].append((dt, server_ms, db_calls))
    return r.status_code, body, dt, server_ms, db_calls


def check(ok, label, meta=None):
    with lock:
        results.append((ok, label))
    extra = ""
    if meta:
        code, _, dt, sms, dbc = meta
        extra = f"  [{code} client {dt * 1000:5.0f} ms | server {sms:4d} ms | db {dbc}]"
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{extra}")
    return ok


def ticket(bus, origin, dest, count=1, ttype="full", cid=None, sess=None):
    payload = {"bus_id": bus, "origin": origin, "destination": dest, "ticket_count": count,
               "ticket_type": ttype, "client_event_id": cid or str(uuid.uuid4())}
    return call("POST", "/api/issue_ticket", sess=sess, json=payload)


def state(bus):
    return call("GET", f"/api/bus_state/{bus}")


def forecast_map(body):
    return {f["stop"]: f["count"] for f in body.get("drop_off_forecast", [])}


def step(title):
    print(f"\n--- {title} ---")


def wait_for_version():
    want = os.environ.get("EXPECT_VERSION")
    code, body, dt, *_ = call("GET", "/api/health")
    print(f"health: {code} {body} ({dt:.2f}s)")
    if want and body.get("version") != want:
        print(f"Expected version {want}, got {body.get('version')}. Aborting.")
        sys.exit(2)


def main():
    print(f"BASE = {BASE}")
    wait_for_version()

    step("1. Reset all 7 buses -> onboard 0")
    for b in BUSES:
        m = call("POST", f"/api/reset_trip/{b}")
        check(m[0] == 200 and m[1].get("onboard") == 0 and m[1].get("current_stop_index") == 0,
              f"reset {b}: onboard={m[1].get('onboard')}", m)
    m = state("AP-16-5001")
    check(m[1].get("stops", [None])[0] == GNT and m[1].get("current_stop_name") == GNT,
          f"AP-16-5001 stops start at GUNTUR RTC: {m[1].get('stops')}", m)

    step("2. AP-16-1234: 3 full ->GUNTUR RTC, 1 zero_fare ->MANGALAGIRI, 1 pass ->TADEPALLI (by name)")
    m = ticket(MAIN, VJA, GNT, count=3)
    check(m[0] == 200 and m[1].get("onboard") == 3 and m[1].get("fare") == 105,
          f"3 full: onboard={m[1].get('onboard')} fare={m[1].get('fare')}", m)
    m = ticket(MAIN, VJA, MAN, ttype="zero_fare")
    check(m[0] == 200 and m[1].get("onboard") == 4 and m[1].get("fare") == 0,
          f"1 zero_fare: onboard={m[1].get('onboard')} fare={m[1].get('fare')}", m)
    m = ticket(MAIN, VJA, TAD, ttype="pass")
    check(m[0] == 200 and m[1].get("onboard") == 5 and m[1].get("fare") == 0,
          f"1 pass: onboard={m[1].get('onboard')} fare={m[1].get('fare')}", m)
    m = state(MAIN)
    fm = forecast_map(m[1])
    check(m[1].get("onboard") == 5 and fm == {TAD: 1, MAN: 1, GNT: 3},
          f"bus_state onboard={m[1].get('onboard')} forecast={fm}", m)
    b = m[1]
    check((b.get("seated"), b.get("empty"), b.get("standing"), b.get("occupancy_pct"),
           b.get("occupied_seats"), b.get("total_capacity")) == (5, 45, 0, 10, 5, 50),
          f"seated/empty/standing/pct/compat = {b.get('seated')}/{b.get('empty')}/{b.get('standing')}/"
          f"{b.get('occupancy_pct')}% occupied_seats={b.get('occupied_seats')} total_capacity={b.get('total_capacity')}")
    check([d["stop"] for d in b.get("dropoffs", [])] == [TAD, MAN, GNT], f"legacy dropoffs={b.get('dropoffs')}")

    step("3. Advance -> 4 (TADEPALLI gone), advance -> 3")
    m = call("POST", f"/api/advance_stop/{MAIN}")
    check(m[0] == 200 and m[1].get("onboard") == 4 and m[1].get("onboard_departing") == 5
          and m[1].get("current_stop_name") == TAD and TAD not in forecast_map(m[1]),
          f"advance: index={m[1].get('current_stop_index')} departing={m[1].get('onboard_departing')} "
          f"onboard={m[1].get('onboard')}", m)
    m = call("POST", f"/api/advance_stop/{MAIN}")
    check(m[0] == 200 and m[1].get("onboard") == 3 and m[1].get("current_stop_name") == MAN,
          f"advance: index={m[1].get('current_stop_index')} onboard={m[1].get('onboard')} "
          f"forecast={forecast_map(m[1])}", m)

    step("4. Late ticket PNBS->GUNTUR RTC (origin behind bus) -> 4")
    m = ticket(MAIN, VJA, GNT)
    check(m[0] == 200 and m[1].get("onboard") == 4, f"late ticket: onboard={m[1].get('onboard')}", m)

    step("5. Same client_event_id twice -> duplicate, onboard unchanged")
    cid = str(uuid.uuid4())
    m1 = ticket(MAIN, MAN, GNT, cid=cid)
    check(m1[0] == 200 and m1[1].get("duplicate") is False and m1[1].get("onboard") == 5,
          f"first send: duplicate={m1[1].get('duplicate')} onboard={m1[1].get('onboard')}", m1)
    m2 = ticket(MAIN, MAN, GNT, cid=cid)
    check(m2[0] == 200 and m2[1].get("duplicate") is True and m2[1].get("onboard") == 5,
          f"second send: duplicate={m2[1].get('duplicate')} onboard={m2[1].get('onboard')}", m2)

    step("6. Invalid tickets -> 422")
    for label, payload in [
        ("destination before origin", {"bus_id": MAIN, "origin": NAM, "destination": TAD}),
        ("unknown bus", {"bus_id": "AP-00-0000", "origin": VJA, "destination": GNT}),
        ("unknown stop", {"bus_id": MAIN, "origin": VJA, "destination": "HYDERABAD"}),
        ("ticket_count 0", {"bus_id": MAIN, "origin": VJA, "destination": GNT, "ticket_count": 0}),
        ("bad ticket_type", {"bus_id": MAIN, "origin": VJA, "destination": GNT, "ticket_type": "vip"}),
        ("gnt-vja bus with vja-gnt order", {"bus_id": "AP-16-5001", "origin": VJA, "destination": GNT}),
    ]:
        m = call("POST", "/api/issue_ticket", json=payload)
        check(m[0] == 422, f"{label}: {m[0]} {str(m[1].get('detail'))[:70]}", m)
    m = state(MAIN)
    check(m[1].get("onboard") == 5, f"onboard unchanged after rejects: {m[1].get('onboard')}", m)

    step("7. Advance 6 more times -> index 5, onboard 0, all 200")
    codes = []
    for _ in range(6):
        m = call("POST", f"/api/advance_stop/{MAIN}")
        codes.append(m[0])
    check(all(c == 200 for c in codes) and m[1].get("current_stop_index") == 5 and m[1].get("onboard") == 0
          and m[1].get("moved") is False,
          f"codes={codes} index={m[1].get('current_stop_index')} onboard={m[1].get('onboard')} "
          f"last moved={m[1].get('moved')}", m)

    step("8. Capacity 3 + 4 full tickets -> seated 3, standing 1, 133%")
    m = call("POST", f"/api/reset_trip/{MAIN}", json={"seat_capacity": 3})
    check(m[0] == 200 and m[1].get("seat_capacity") == 3, f"reset cap 3: {m[1].get('seat_capacity')}", m)
    for _ in range(4):
        ticket(MAIN, VJA, GNT)
    m = state(MAIN)
    b = m[1]
    check((b.get("onboard"), b.get("seated"), b.get("empty"), b.get("standing"), b.get("occupancy_pct")) == (4, 3, 0, 1, 133),
          f"onboard {b.get('onboard')} seated {b.get('seated')} empty {b.get('empty')} "
          f"standing {b.get('standing')} pct {b.get('occupancy_pct')}", m)

    step("9. CONCURRENCY: each bus reset, 5 parallel qty-1 tickets -> onboard exactly 5")
    for bus in BUSES:
        call("POST", f"/api/reset_trip/{bus}")
        o, d = (GNT, VJA) if bus in GNT_VJA else (VJA, GNT)
        barrier = threading.Barrier(5)
        out = [None] * 5

        def fire(i, bus=bus, o=o, d=d, barrier=barrier, out=out):
            s = requests.Session()
            barrier.wait()
            out[i] = ticket(bus, o, d, sess=s)

        with ThreadPoolExecutor(5) as ex:
            list(ex.map(fire, range(5)))
        codes = [r[0] for r in out]
        times = [f"{r[2]:.2f}s" for r in out]
        m = state(bus)
        check(all(c == 200 for c in codes) and m[1].get("onboard") == 5,
              f"{bus} ({o}->{d}): codes={codes} times={times} onboard={m[1].get('onboard')}", m)

    step("10. Batch /api/bus_states returns all 7 with correct onboard")
    batch_times = []
    for _ in range(3):
        m = call("GET", "/api/bus_states?ids=" + ",".join(BUSES))
        batch_times.append(m)
    m = batch_times[-1]
    buses = m[1].get("buses", {})
    got = {b: buses.get(b, {}).get("onboard") for b in BUSES}
    check(m[0] == 200 and all(v == 5 for v in got.values()), f"onboard per bus: {got}", m)
    check(buses.get("AP-16-5002", {}).get("stops", [None])[0] == GNT, "AP-16-5002 stops start at GUNTUR RTC")
    best_server = min(x[3] for x in batch_times)
    best_client = min(x[2] for x in batch_times)
    check(best_server < 1000 and best_client < 1.0,
          f"batch warm time: client best {best_client * 1000:.0f} ms, server best {best_server} ms, "
          f"db calls {m[4]}")

    step("11. Reset all 7 buses with capacity 50")
    for b in BUSES:
        m = call("POST", f"/api/reset_trip/{b}", json={"seat_capacity": 50})
        check(m[0] == 200 and m[1].get("onboard") == 0 and m[1].get("seat_capacity") == 50, f"reset {b}", m)

    print("\n=== RESPONSE TIMES (server = X-Response-Time-ms, client includes network) ===")
    print(f"{'endpoint':22} {'n':>3} {'client med':>10} {'client max':>10} {'server med':>10} "
          f"{'server max':>10} {'db max':>6}")
    for ep, rows in sorted(timings.items()):
        cl = sorted(r[0] for r in rows)
        sv = sorted(r[1] for r in rows)
        dbm = max(r[2] for r in rows)
        print(f"{ep:22} {len(rows):3d} {cl[len(cl) // 2] * 1000:8.0f}ms {cl[-1] * 1000:8.0f}ms "
              f"{sv[len(sv) // 2]:8d}ms {sv[-1]:8d}ms {dbm:6d}")

    passed = sum(1 for ok, _ in results if ok)
    print(f"\nRESULT: {passed}/{len(results)} checks passed")
    for ok, label in results:
        if not ok:
            print(f"  FAILED: {label}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
