"""
Browser test for the passenger PWA (index.html, Stage 3), driven headlessly in Microsoft Edge via Playwright.
Tickets / stop changes are made through the backend API (as the ETM would) and the page must reflect them.

Setup (once, PowerShell):
    py -m pip install playwright requests
Run:
    py tests\\test_pwa_browser.py
    $env:HEADED = "1"; py tests\\test_pwa_browser.py

NOTE: resets trips on all 7 buses and inserts test tickets; everything is reset to capacity 50 at the end.
"""
import functools
import http.server
import os
import re
import sys
import threading
import time
import uuid

import requests
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = "https://prototype2-qqw6.onrender.com"
BUSES = ["AP-16-1234", "AP-16-4023", "AP-16-4024", "AP-16-4025", "AP-16-4026", "AP-16-5001", "AP-16-5002"]
VJA, TAD, MAN, NAM, PED, GNT = ("VIJAYAWADA PNBS", "TADEPALLI", "MANGALAGIRI", "NAMBURU", "PEDDAKAKANI", "GUNTUR RTC")
results = []
api = requests.Session()


def check(ok, label):
    results.append((ok, label))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    return ok


def serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
    handler.log_message = lambda *a: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/index.html"


def reset(bus, cap=50):
    r = api.post(f"{BACKEND}/api/reset_trip/{bus}", json={"seat_capacity": cap}, timeout=60)
    assert r.status_code == 200, r.text


def ticket(bus, o, d, n=1, t="full"):
    r = api.post(f"{BACKEND}/api/issue_ticket", timeout=60, json={
        "bus_id": bus, "origin": o, "destination": d, "ticket_count": n, "ticket_type": t,
        "client_event_id": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    return r.json()


def advance(bus):
    r = api.post(f"{BACKEND}/api/advance_stop/{bus}", timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


def wait_js(page, expr, arg=None, timeout=20):
    t0 = time.perf_counter()
    page.wait_for_function(f"(a) => {{ {expr} }}", arg=arg, timeout=timeout * 1000, polling=100)
    return time.perf_counter() - t0


def text_is(page, el_id, value, timeout=10):
    """Wait until #el_id has exactly `value`; return seconds waited (or None on timeout)."""
    try:
        return wait_js(page, "return document.getElementById(a[0]).textContent.trim() === a[1]", [el_id, value], timeout)
    except Exception:
        return None


def card_badges(page):
    return page.evaluate("""Object.fromEntries([...document.querySelectorAll('#bus-list-container .bus-item')].map(d => {
        const b = d.querySelector('.eta-badge');
        return [d.querySelector('b').textContent, [b.textContent.trim(), getComputedStyle(b).color]];
    }))""")


def timeline(page):
    return page.evaluate("""[...document.querySelectorAll('#rt-timeline-stops .rt-stop')].map(s =>
        [s.querySelector('.rt-stop-name').textContent.trim(), s.querySelector('.rt-time-val').textContent.trim()])""")


def dropoff_rows(page):
    return page.evaluate("""[...document.querySelectorAll('#dof-stop-list .dof-stop-row')].map(r =>
        [r.querySelector('.dof-stop-name').textContent.replace('📍','').trim(), r.querySelector('.dof-count-badge').textContent.trim(),
         r.querySelector('.dof-stop-eta').textContent.trim()])""")


GREEN, AMBER, RED = "rgb(22, 163, 74)", "rgb(161, 98, 7)", "rgb(220, 38, 38)"


def main():
    httpd, url = serve()
    print(f"Serving {ROOT} at {url}")
    print("Preparing buses via API ...")
    for b in BUSES:
        reset(b)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=not os.environ.get("HEADED"))
        page = browser.new_context(viewport={"width": 420, "height": 860}).new_page()
        reqs = []
        page.on("request", lambda r: reqs.append((time.perf_counter(), r.url)) if BACKEND in r.url else None)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        def api_reqs(since, pattern):
            return [u for t, u in reqs if t >= since and re.search(pattern, u)]

        print("\n--- 1. Warm-up ---")
        t0 = time.perf_counter()
        page.goto(url)
        page.wait_for_timeout(500)
        check(any("/api/health" in u for _, u in reqs), "GET /api/health sent on page load")

        print("\n--- 2. Bus list: one /api/bus_states request per poll, badges ---")
        reset("AP-16-4024", 5)
        reset("AP-16-4025", 3)
        wait_js(page, "return screenActive('auth-screen')", timeout=10)   # splash -> login screen (2.8s timer)
        page.evaluate("login(); selectStop('from', 'VIJAYAWADA PNBS'); selectStop('to', 'GUNTUR RTC'); search();")
        text_is(page, "route-tag", "🚌 VIJAYAWADA PNBS  →  GUNTUR RTC", 5)
        wait_js(page, "return [...document.querySelectorAll('#bus-list-container .eta-badge')].every(b => b.textContent.trim() !== '—')", timeout=15)
        badges = card_badges(page)
        check(set(badges) == {"AP16Z-4022", "AP16Z-4023", "AP16Z-4024", "AP16Z-4025", "AP16Z-4026"},
              f"vja-gnt list: {sorted(badges)}")
        check(badges["AP16Z-4022"] == ["0/50", GREEN], f"empty bus: {badges['AP16Z-4022']}")
        since = time.perf_counter()
        page.wait_for_timeout(6500)
        batch = api_reqs(since, r"/api/bus_states\?ids=")
        single = api_reqs(since, r"/api/bus_state/")
        check(len(batch) >= 2 and not single, f"in 6.5s: {len(batch)} bus_states requests, {len(single)} per-bus requests")
        check(bool(batch) and all(b in batch[-1] for b in BUSES[:5]) and "5001" not in batch[-1],
              f"batch asks only visible buses: {batch[-1].split('?')[1] if batch else None}")

        for _ in range(3):
            ticket("AP-16-4023", VJA, GNT)
        ticket("AP-16-4024", VJA, GNT, n=3)       # 3/5 = 60% -> amber
        t_api = time.perf_counter()
        ticket("AP-16-4025", VJA, GNT, n=3)       # 3/3 -> Full
        try:
            wait_js(page, """const t = [...document.querySelectorAll('#bus-list-container .bus-item')]
                .map(d => d.querySelector('.eta-badge').textContent.trim()); return t.includes('Full') && t.includes('3/5') && t.includes('3/50')""",
                    timeout=10)
        except Exception:
            pass
        dt = time.perf_counter() - t_api
        badges = card_badges(page)
        check(badges["AP16Z-4023"] == ["3/50", GREEN], f"4023: {badges['AP16Z-4023']}")
        check(badges["AP16Z-4024"] == ["3/5", AMBER], f"4024 (60%): {badges['AP16Z-4024']}")
        check(badges["AP16Z-4025"] == ["Full", RED], f"4025 (3/3): {badges['AP16Z-4025']}")
        check(dt < 5, f"list updated {dt:.2f}s after the last ticket (target < 5s)")
        reset("AP-16-4024")
        reset("AP-16-4025")

        print("\n--- 3. Details page AP16Z-4022: acceptance scenario ---")
        reset("AP-16-1234")
        page.evaluate("openRouteTracking('AP16Z-4022')")
        text_is(page, "occ-card-occ", "0", 10)
        ticket("AP-16-1234", VJA, GNT, n=3)
        ticket("AP-16-1234", VJA, MAN, t="zero_fare")
        t_api = time.perf_counter()
        ticket("AP-16-1234", VJA, TAD, t="pass")
        text_is(page, "occ-card-occ", "5", 10)
        dt = time.perf_counter() - t_api
        occ = [page.inner_text(f"#{i}") for i in ("occ-card-occ", "occ-card-emp", "occ-card-std")]
        check(occ == ["5", "45", "0"] and dt < 5, f"Occupied/Empty/Standing = {occ}, shown {dt:.2f}s after the last ticket")
        check(page.inner_text("#occ-pct-label") == "10% capacity", f"label: {page.inner_text('#occ-pct-label')}")
        tl = timeline(page)
        check(tl[0] == [VJA, "Now"] and all(re.fullmatch(r"ETA \d\d:\d\d( [AP]M)?\s*Scheduled", t, re.I) for _, t in tl[1:]),
              f"timeline: {tl}")
        check(page.inner_text("#info-eta") == "15 min (scheduled)", f"next stop ETA: {page.inner_text('#info-eta')}")
        page.evaluate("switchRTTab('dropoff')")
        rows = dropoff_rows(page)
        check([(r[0], r[1]) for r in rows] == [(TAD, "1 pax"), (MAN, "1 pax"), (GNT, "3 pax")], f"drop-off rows: {rows}")
        foot = (page.inner_text("#dof-total-onboard"), page.inner_text("#dof-after-next"))
        check(foot == ("5", "4"), f"footer current onboard / after next stop: {foot}")

        t_api = time.perf_counter()
        advance("AP-16-1234")
        text_is(page, "dof-total-onboard", "4", 10)
        dt = time.perf_counter() - t_api
        rows = dropoff_rows(page)
        foot = (page.inner_text("#dof-total-onboard"), page.inner_text("#dof-after-next"))
        check(foot == ("4", "3") and TAD not in [r[0] for r in rows] and dt < 5,
              f"after advance ({dt:.2f}s): footer {foot}, rows {[(r[0], r[1]) for r in rows]}")
        page.evaluate("switchRTTab('fullroute')")
        tl = timeline(page)
        check(tl[0] == [VJA, "Departed"] and tl[1] == [TAD, "Now"], f"timeline after advance: {tl[:3]}")
        advance("AP-16-1234")
        check(text_is(page, "occ-card-occ", "3", 10) is not None, "second advance -> onboard 3")

        print("\n--- 4. Paused while hidden, immediate poll when visible ---")
        page.evaluate("Object.defineProperty(document, 'hidden', { value: true, configurable: true })")
        page.wait_for_timeout(300)
        since = time.perf_counter()
        page.wait_for_timeout(6500)
        check(not api_reqs(since, r"/api/bus_state"), f"hidden: {len(api_reqs(since, r'/api/bus_state'))} requests in 6.5s")
        page.evaluate("Object.defineProperty(document, 'hidden', { value: false, configurable: true }); "
                      "document.dispatchEvent(new Event('visibilitychange'))")
        since = time.perf_counter()
        page.wait_for_timeout(400)
        check(len(api_reqs(since - 0.05, r"/api/bus_state/AP-16-1234")) >= 1, "visible again: polled immediately")

        print("\n--- 5. Stale banner after 15s without data ---")
        page.route(f"{BACKEND}/api/bus_state/**", lambda r: r.abort())
        t0 = time.perf_counter()
        wait_js(page, "return document.getElementById('stale-banner').style.display === 'block'", timeout=25)
        dt = time.perf_counter() - t0
        check(12 <= dt <= 17, f"banner after {dt:.1f}s: '{page.inner_text('#stale-banner')}'")
        page.unroute(f"{BACKEND}/api/bus_state/**")
        wait_js(page, "return document.getElementById('stale-banner').style.display === 'none'", timeout=10)
        check(True, "banner hidden again once data flows")

        print("\n--- 6. Capacity 3 + 4 tickets: standing on details, 'Full' on list ---")
        reset("AP-16-1234", 3)
        for _ in range(4):
            ticket("AP-16-1234", VJA, GNT)
        text_is(page, "occ-card-std", "1", 10)
        occ = [page.inner_text(f"#{i}") for i in ("occ-card-occ", "occ-card-emp", "occ-card-std")]
        check(occ == ["3", "0", "1"] and page.inner_text("#occ-pct-label") == "133% capacity",
              f"details: {occ}, {page.inner_text('#occ-pct-label')}")
        page.evaluate("navigate('user-results'); renderUserList();")
        wait_js(page, """return [...document.querySelectorAll('#bus-list-container .bus-item')]
            .some(d => d.textContent.includes('AP16Z-4022') && d.querySelector('.eta-badge').textContent.trim() === 'Full')""", timeout=10)
        check(card_badges(page)["AP16Z-4022"] == ["Full", RED], f"list badge: {card_badges(page)['AP16Z-4022']}")
        reset("AP-16-1234")

        print("\n--- 7. gnt-vja bus AP16Z-5001: timeline and forecast in its own direction ---")
        reset("AP-16-5001")
        ticket("AP-16-5001", GNT, VJA, n=2)
        ticket("AP-16-5001", GNT, MAN)
        page.evaluate("selectStop('from', 'GUNTUR RTC'); selectStop('to', 'VIJAYAWADA PNBS'); search();")
        wait_js(page, "return document.querySelectorAll('#bus-list-container .bus-item').length === 2", timeout=5)
        wait_js(page, "return [...document.querySelectorAll('#bus-list-container .eta-badge')].every(b => b.textContent.trim() !== '—')", timeout=10)
        badges = card_badges(page)
        check(badges.get("AP16Z-5001", [None])[0] == "3/50" and "AP16Z-5002" in badges, f"gnt-vja list: {badges}")
        page.evaluate("openRouteTracking('AP16Z-5001')")
        text_is(page, "occ-card-occ", "3", 10)
        tl = timeline(page)
        check([n for n, _ in tl] == [GNT, PED, NAM, MAN, TAD, VJA] and tl[0][1] == "Now", f"timeline order: {[n for n, _ in tl]}")
        check(page.inner_text("#rt-route-name") == "Route: Guntur → Vijayawada", page.inner_text("#rt-route-name"))
        check(page.inner_text("#info-eta") == "15 min (scheduled)", f"next stop ETA: {page.inner_text('#info-eta')}")
        page.evaluate("switchRTTab('dropoff')")
        rows = dropoff_rows(page)
        check([(r[0], r[1]) for r in rows] == [(MAN, "1 pax"), (VJA, "2 pax")], f"forecast order: {rows}")

        print("\n--- 8. Admin list + live overlay ---")
        page.evaluate("selectRole('admin'); login();")
        wait_js(page, "return [...document.querySelectorAll('#admin-bus-list .bus-item')].every(d => !d.textContent.includes('—'))", timeout=10)
        adm = page.evaluate("[...document.querySelectorAll('#admin-bus-list .bus-item')].map(d => d.innerText.replace(/\\s+/g, ' '))")
        check(len(adm) == 7 and any("AP16Z-5001 Seats: 3/50" in a for a in adm), f"admin list: {adm}")
        check("Sample" in page.inner_text("#admin-dashboard"), "admin totals still tagged Sample")
        page.evaluate("openLive('AP16Z-5001')")
        stats = [page.inner_text(f"#{i}") for i in ("stat-occ", "stat-emp", "stat-std")]
        ov = page.inner_text("#live-overlay-dropoffs")
        check(stats == ["3", "47", "0"] and "MANGALAGIRI" in ov and "Simulated" in page.inner_text("#speed-badge"),
              f"overlay stats {stats}, drop-offs '{ov.strip()}'")
        page.evaluate("closeLive()")

        check(not errors, f"no page errors: {errors}")
        browser.close()
    httpd.shutdown()

    print("\nCleaning up: reset all 7 buses (capacity 50)")
    for b in BUSES:
        reset(b)

    passed = sum(1 for ok, _ in results if ok)
    print(f"\nRESULT: {passed}/{len(results)} checks passed")
    for ok, label in results:
        if not ok:
            print(f"  FAILED: {label}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
