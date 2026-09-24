"""
Stage 0 diagnostic for the TravelloBus backend (no code changes, read + write tickets only).

Usage (PowerShell):
    py tests\\diagnose.py
    $env:BASE = "http://localhost:8000"; py tests\\diagnose.py

What it does:
  a) Warm-up: times the first request (cold start) to /api/health, falling back to /docs.
  b) For each of the 7 buses: read /api/bus_state, fire 3 tickets in parallel threads using
     the exact payload etm.html sends today, then read /api/bus_state again (immediately,
     and again after a short wait) and compare expected vs actual increase.
  c) Load check: repeat (b) for one non-4022 bus while simulating a PWA polling all 7 buses,
     to see whether ticket requests get serialized behind reads.

NOTE: this inserts real rows into ticket_events (3 per bus + 3 for the load check).
"""
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = os.environ.get("BASE", "https://prototype2-qqw6.onrender.com").rstrip("/")
STOPS = ["VIJAYAWADA PNBS", "TADEPALLI", "MANGALAGIRI", "NAMBURU", "PEDDAKAKANI", "GUNTUR RTC"]
# Same ids/routes as etm.html busList
BUSES = [
    ("AP-16-1234", "AP16Z-4022", "vja-gnt"),
    ("AP-16-4023", "AP16Z-4023", "vja-gnt"),
    ("AP-16-4024", "AP16Z-4024", "vja-gnt"),
    ("AP-16-4025", "AP16Z-4025", "vja-gnt"),
    ("AP-16-4026", "AP16Z-4026", "vja-gnt"),
    ("AP-16-5001", "AP16Z-5001", "gnt-vja"),
    ("AP-16-5002", "AP16Z-5002", "gnt-vja"),
]
TIMEOUT = 90


def timed(method, path, **kw):
    t0 = time.perf_counter()
    try:
        r = requests.request(method, BASE + path, timeout=TIMEOUT, **kw)
        dt = time.perf_counter() - t0
        try:
            body = r.json()
        except ValueError:
            body = r.text[:200]
        return r.status_code, dt, body
    except requests.RequestException as e:
        return f"ERR {type(e).__name__}", time.perf_counter() - t0, str(e)[:200]


def etm_payload(bus_id, route):
    # etm.html defaults after "OK": vja-gnt source idx 0 -> dest idx 1;
    # gnt-vja source idx 5 -> dest idx 4. Names only, no ids/types.
    if route == "vja-gnt":
        o, d = STOPS[0], STOPS[1]
    else:
        o, d = STOPS[5], STOPS[4]
    return {"bus_id": bus_id, "origin": o, "destination": d, "ticket_count": 1}


def occ(body):
    return body.get("occupied_seats") if isinstance(body, dict) else None


def section(title):
    print("\n" + "=" * 78 + "\n" + title + "\n" + "=" * 78)


def warmup():
    section(f"a) COLD START  (BASE = {BASE})")
    code, dt, body = timed("GET", "/api/health")
    print(f"GET /api/health  -> {code}  {dt:6.2f}s  {str(body)[:80]}")
    if code != 200:
        code, dt, _ = timed("GET", "/docs")
        print(f"GET /docs        -> {code}  {dt:6.2f}s   (health missing; /docs used as warm-up)")
    print(f"Cold-start / first-request time: {dt:.2f}s")
    code, dt2, _ = timed("GET", "/docs")
    print(f"Second request (/docs, warm):    {dt2:.2f}s")


def fire_tickets(bus_id, route, n=3):
    payload = etm_payload(bus_id, route)
    results = [None] * n
    barrier = threading.Barrier(n)

    def one(i):
        barrier.wait()
        results[i] = timed("POST", "/api/issue_ticket", json=payload)

    with ThreadPoolExecutor(n) as ex:
        list(ex.map(one, range(n)))
    return payload, results


def per_bus():
    section("b) PER-BUS: 3 parallel tickets (exact etm.html payload)")
    summary = []
    for bus_id, plate, route in BUSES:
        print(f"\n--- {bus_id} ({plate}, {route}) ---")
        c0, t0, b0 = timed("GET", f"/api/bus_state/{bus_id}")
        before = occ(b0)
        print(f"  bus_state before : {c0}  {t0:5.2f}s  occupied_seats={before}  "
              f"body={str(b0)[:120]}")
        payload, res = fire_tickets(bus_id, route)
        print(f"  payload          : {payload}")
        for i, (c, dt, body) in enumerate(res):
            print(f"  ticket #{i + 1}        : {c}  {dt:5.2f}s  {str(body)[:90]}")
        ok = sum(1 for c, _, _ in res if c == 200)
        c1, t1, b1 = timed("GET", f"/api/bus_state/{bus_id}")
        after = occ(b1)
        time.sleep(3)
        c2, t2, b2 = timed("GET", f"/api/bus_state/{bus_id}")
        after3 = occ(b2)
        inc = (after - before) if isinstance(after, int) and isinstance(before, int) else None
        inc3 = (after3 - before) if isinstance(after3, int) and isinstance(before, int) else None
        print(f"  bus_state after  : {c1}  {t1:5.2f}s  occupied_seats={after}")
        print(f"  bus_state +3s    : {c2}  {t2:5.2f}s  occupied_seats={after3}")
        verdict = "OK" if inc == 3 and inc3 == 3 else "MISMATCH"
        print(f"  expected +3 | 200s={ok}/3 | actual +{inc} (immediately), +{inc3} (after 3s)  -> {verdict}")
        summary.append((bus_id, plate, c0, ok, inc, inc3, verdict,
                        max(dt for _, dt, _ in res), t0))
    return summary


def load_check():
    section("c) LOAD CHECK: 3 tickets on AP-16-4023 while a simulated PWA polls all 7 buses")
    stop = threading.Event()
    poll_times = []

    def pwa():
        while not stop.is_set():
            with ThreadPoolExecutor(7) as ex:
                rs = list(ex.map(lambda b: timed("GET", f"/api/bus_state/{b[0]}"), BUSES))
            poll_times.extend(dt for _, dt, _ in rs)
            time.sleep(0.5)

    th = threading.Thread(target=pwa, daemon=True)
    th.start()
    time.sleep(1.0)
    _, res = fire_tickets("AP-16-4023", "vja-gnt")
    stop.set()
    th.join(timeout=TIMEOUT)
    for i, (c, dt, body) in enumerate(res):
        print(f"  ticket #{i + 1} under load: {c}  {dt:5.2f}s  {str(body)[:80]}")
    if poll_times:
        poll_times.sort()
        print(f"  bus_state under load: n={len(poll_times)}  min={poll_times[0]:.2f}s  "
              f"median={poll_times[len(poll_times) // 2]:.2f}s  max={poll_times[-1]:.2f}s")


def main():
    print(f"Python {sys.version.split()[0]}  requests {requests.__version__}")
    warmup()
    summary = per_bus()
    load_check()
    section("SUMMARY")
    print(f"{'bus_id':12} {'plate':11} {'state':>5} {'200s':>5} {'+now':>5} {'+3s':>5} "
          f"{'max tkt s':>9} {'state s':>7}  verdict")
    for bus_id, plate, c0, ok, inc, inc3, v, mx, ts in summary:
        print(f"{bus_id:12} {plate:11} {str(c0):>5} {ok:>3}/3 {str(inc):>5} {str(inc3):>5} "
              f"{mx:9.2f} {ts:7.2f}  {v}")


if __name__ == "__main__":
    main()
