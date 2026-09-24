"""
Browser test for etm.html (Stage 2), driven headlessly in Microsoft Edge via Playwright.
Talks to the backend hard-coded in etm.html (BACKEND_URL = Render).

Setup (once, PowerShell):
    py -m pip install playwright
Run:
    py tests\\test_etm_browser.py            # headless
    $env:HEADED = "1"; py tests\\test_etm_browser.py

NOTE: resets the trips of AP-16-1234 and AP-16-5001 and prints real test tickets; both are reset again at the end.
"""
import functools
import http.server
import os
import re
import sys
import threading
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = "https://prototype2-qqw6.onrender.com"
results = []


def check(ok, label):
    results.append((ok, label))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    return ok


def serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
    handler.log_message = lambda *a: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/etm.html"


def sync_text(page):
    return page.inner_text("#syncStatus")


def wait_js(page, expr, arg=None, timeout=20):
    """Wait until JS expression (function body taking `a`) is truthy; return seconds waited."""
    t0 = time.perf_counter()
    page.wait_for_function(f"(a) => {{ {expr} }}", arg=arg, timeout=timeout * 1000, polling=50)
    return time.perf_counter() - t0


def wait_sync(page, needle, timeout=20):
    return wait_js(page, "return document.getElementById('syncStatus').textContent.includes(a)", needle, timeout)


def key(page, onclick):
    page.click(f"button[onclick=\"{onclick}\"]")


C, DOWN, ENT, FN = "confirmSelection()", "navigate('down')", "printTicket()", "cycleType()"


def queue_len(page):
    return page.evaluate("readQueue().length")


def reset_bus(page):
    page.evaluate("document.getElementById('demoPanel').open = true")
    key(page, "demoAction('reset')")
    wait_js(page, "return document.getElementById('totalTkts').textContent === '0' && !demoBusy", timeout=30)


def table(page):
    return page.evaluate("""[...document.querySelectorAll('#dropTableBody tr')].map(t =>
        [t.children[0].textContent, t.children[1].textContent, t.children[2].textContent])""")


def main():
    httpd, url = serve()
    print(f"Serving {ROOT} at {url}")
    sent = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=not os.environ.get("HEADED"))
        ctx = browser.new_context()
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        page.on("request", lambda r: sent.append(r.post_data_json) if "/api/issue_ticket" in r.url and r.method == "POST" else None)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        print("\n--- 1. Warm-up and polling at the bus-selection step ---")
        page.goto(url)
        early = (page.inner_text("#connBadge"), sync_text(page))
        check("Connecting" in early[0] and "Connecting" in early[1], f"initial: badge='{early[0]}' status='{early[1]}'")
        t = wait_js(page, "return document.getElementById('connBadge').textContent.includes('Connected')", timeout=90)
        check(True, f"health answered, badge 'Connected to cloud' after {t:.2f}s (status: '{sync_text(page)}')")
        t = wait_js(page, "return document.getElementById('totalTkts').textContent !== '—'", timeout=30)
        check(page.evaluate("step") == 0, f"bus_state shown while still on bus selection (step 0) after {t:.2f}s; "
                                          f"default bus = {page.evaluate('activeBus().id')}")
        check(page.evaluate("localStorage.getItem('etmNewEvent')") is None, "no etmNewEvent written")
        uuid_fb = page.evaluate("""(() => { const f = crypto.randomUUID; try { crypto.randomUUID = undefined; return newUUID(); }
                                   finally { crypto.randomUUID = f; } })()""")
        check(re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", uuid_fb) is not None,
              f"UUID fallback without crypto.randomUUID: {uuid_fb}")

        print("\n--- 2. AP16Z-4022 demo: reset, 3 Full ->GUNTUR RTC, 1 Stree Shakti ->MANGALAGIRI, 1 Pass ->TADEPALLI ---")
        reset_bus(page)
        check(page.inner_text("#totalTkts") == "0" and page.inner_text("#totalRev") == "₹0",
              f"after reset: onboard {page.inner_text('#totalTkts')}, revenue {page.inner_text('#totalRev')}")
        key(page, C)                                      # bus -> source (PNBS)
        key(page, C)                                      # source -> dest
        for _ in range(4):
            key(page, DOWN)                               # TADEPALLI -> GUNTUR RTC
        key(page, C)                                      # dest -> qty
        key(page, "pressNum(3)")
        t0 = time.perf_counter()
        key(page, ENT)
        first = sync_text(page)
        wait_sync(page, "✓ Synced — 3 onboard")
        dt = time.perf_counter() - t0
        check("Sending" in first, f"immediately after ENT: '{first}'")
        check(dt < 2.0, f"'✓ Synced — 3 onboard' {dt:.2f}s after ENT (target < 2s)")

        key(page, C); key(page, DOWN)                     # source PNBS -> dest MANGALAGIRI
        key(page, C)
        key(page, FN)
        lt = page.inner_text("#lineType")
        check(lt == "TYPE: STREE SHAKTI ₹0", f"FN once -> '{lt}'")
        t0 = time.perf_counter(); key(page, ENT); wait_sync(page, "✓ Synced — 4 onboard")
        dt = time.perf_counter() - t0
        check(page.inner_text("#lineType") == "TYPE: FULL ₹35", f"type back to Full after ticket; synced in {dt:.2f}s")

        key(page, C); key(page, C)                        # source PNBS -> dest TADEPALLI (default) -> qty
        key(page, FN); key(page, FN)
        lt = page.inner_text("#lineType")
        check(lt == "TYPE: PASS ₹0", f"FN twice -> '{lt}'")
        key(page, FN)
        check(page.inner_text("#lineType") == "TYPE: FULL ₹35", "FN three times cycles back to Full")
        key(page, FN); key(page, FN)
        t0 = time.perf_counter(); key(page, ENT); wait_sync(page, "✓ Synced — 5 onboard")
        check(True, f"pass synced in {time.perf_counter() - t0:.2f}s")

        tb = table(page)
        counts = {r[0]: r[1] for r in tb}
        check(page.inner_text("#totalTkts") == "5" and page.inner_text("#totalRev") == "₹105",
              f"onboard {page.inner_text('#totalTkts')}, est. revenue {page.inner_text('#totalRev')}")
        check(counts.get("TADEPALLI") == "1" and counts.get("MANGALAGIRI") == "1" and counts.get("GUNTUR RTC") == "3",
              f"drop table: {tb}")
        last = sent[-1] or {}
        keys = {"bus_id", "origin", "destination", "origin_index", "destination_index", "ticket_count",
                "ticket_type", "client_event_id"}
        check(keys <= set(last) and last["ticket_type"] == "pass" and last["destination_index"] == 1,
              f"payload fields: {last}")
        types = [s.get("ticket_type") for s in sent[-3:]]
        check(types == ["full", "zero_fare", "pass"], f"ticket types sent: {types}")

        print("\n--- 3. Demo controls: advance -> 4, advance -> 3 ---")
        info0 = page.inner_text("#demoStopInfo")
        key(page, "demoAction('advance')")
        wait_js(page, "return document.getElementById('totalTkts').textContent === '4' && !demoBusy")
        info1 = page.inner_text("#demoStopInfo")
        key(page, "demoAction('advance')")
        wait_js(page, "return document.getElementById('totalTkts').textContent === '3' && !demoBusy")
        info2 = page.inner_text("#demoStopInfo")
        check("VIJAYAWADA PNBS" in info0 and "now at TADEPALLI" in info1 and "now at MANGALAGIRI" in info2,
              f"stop info: '{info0}' | '{info1}' | '{info2}'")
        tb = table(page)
        check([r[2] for r in tb] == ["Passed", "Passed", "Bus here", "Ahead", "Ahead", "Ahead"], f"statuses: {[r[2] for r in tb]}")
        check(page.evaluate("currentSourceIdx") == 2, "next boarding point defaults to the bus's current stop (MANGALAGIRI)")

        print("\n--- 4. Network down: ticket kept, retried, survives reload ---")
        page.route(f"{BACKEND}/api/issue_ticket", lambda r: r.abort())
        key(page, C); key(page, C); key(page, ENT)        # MANGALAGIRI -> NAMBURU
        wait_sync(page, "retry in")
        stored = page.evaluate("JSON.parse(localStorage.getItem('etmTicketQueue')).length")
        check(stored == 1, f"status '{sync_text(page)}', {stored} ticket saved in localStorage")
        page.reload()                                     # power key does location.reload()
        wait_js(page, "return document.getElementById('syncStatus').textContent.includes('pending')", timeout=15)
        check(queue_len(page) == 1, f"after reload: queue {queue_len(page)}, status '{sync_text(page)}'")
        page.unroute(f"{BACKEND}/api/issue_ticket")
        t0 = time.perf_counter()
        page.evaluate("window.dispatchEvent(new Event('online'))")
        wait_js(page, "return readQueue().length === 0", timeout=20)
        check(True, f"flushed {time.perf_counter() - t0:.2f}s after 'online' event")
        t = wait_js(page, "return document.getElementById('totalTkts').textContent === '4'", timeout=10)
        check(True, "onboard 4 after the queued ticket synced")

        print("\n--- 5. 5xx retried with backoff; 4xx dropped without blocking the queue ---")
        hits = {"n": 0}

        def flaky(route):
            hits["n"] += 1
            if hits["n"] == 1:
                route.fulfill(status=503, body='{"detail":"test 503"}', content_type="application/json")
            else:
                route.continue_()
        page.route(f"{BACKEND}/api/issue_ticket", flaky)
        page.evaluate("""enqueueTicket({bus_id:'AP-16-1234', origin:'MANGALAGIRI', destination:'GUNTUR RTC',
                         origin_index:2, destination_index:5, ticket_count:1, ticket_type:'full', client_event_id:newUUID()}); flushQueue();""")
        wait_js(page, "return readQueue().length === 0", timeout=20)
        logs = page.inner_text("#logBox")
        check(hits["n"] >= 2 and "HTTP 503" in logs and "retrying in 1s" in logs, f"503 then success ({hits['n']} attempts)")
        page.unroute(f"{BACKEND}/api/issue_ticket")
        page.evaluate("""enqueueTicket({bus_id:'AP-16-1234', origin:'GUNTUR RTC', destination:'VIJAYAWADA PNBS',
                         ticket_count:1, ticket_type:'full', client_event_id:newUUID()});
                         enqueueTicket({bus_id:'AP-16-1234', origin:'MANGALAGIRI', destination:'GUNTUR RTC',
                         ticket_count:1, ticket_type:'full', client_event_id:newUUID()}); flushQueue();""")
        wait_js(page, "return readQueue().length === 0", timeout=20)
        wait_sync(page, "✓ Synced — 6 onboard")
        red = page.locator(".log-entry.log-error").first.inner_text()
        check("REJECTED (HTTP 422)" in red and "not after origin" in red, f"red log: {red[:110]}")
        check(True, "the good ticket behind the rejected one synced (onboard 6)")

        print("\n--- 6. AP16Z-5001 (gnt-vja): 5 tickets under 1s apart ---")
        page.reload()
        wait_js(page, "return document.getElementById('totalTkts').textContent !== '—'", timeout=30)
        for _ in range(5):
            key(page, DOWN)
        check(page.evaluate("activeBus().id") == "AP-16-5001", f"selected {page.evaluate('activeBus().plate')} at step 0")
        wait_js(page, "return busState && busState.bus_id === 'AP-16-5001'", timeout=15)
        reset_bus(page)
        key(page, C)                                      # bus -> source GUNTUR RTC
        check(page.inner_text("#selection") == "GUNTUR RTC", f"default source: {page.inner_text('#selection')}")
        n0 = len(sent)
        t0 = time.perf_counter()
        for i in range(5):
            key(page, C); key(page, C); key(page, ENT)    # GUNTUR RTC -> PEDDAKAKANI, qty 1
        t_print = time.perf_counter() - t0
        wait_js(page, "return readQueue().length === 0", timeout=30)
        wait_sync(page, "✓ Synced — 5 onboard", timeout=10)
        t_all = time.perf_counter() - t0
        new = sent[n0:]
        check(t_print < 1.0, f"5 tickets printed in {t_print:.2f}s")
        check(page.inner_text("#totalTkts") == "5", f"onboard {page.inner_text('#totalTkts')} (all 5 confirmed {t_all:.2f}s after first ENT)")
        cids = {s["client_event_id"] for s in new if s}
        check(len(cids) == 5 and all(s["origin_index"] == 0 and s["destination_index"] == 1 for s in new),
              f"{len(new)} requests, {len(cids)} unique ids, direction indices {[(s['origin_index'], s['destination_index']) for s in new]}")
        tb = table(page)
        check(tb[0][0] == "GUNTUR RTC" and tb[-1][0] == "VIJAYAWADA PNBS" and dict((r[0], r[1]) for r in tb).get("PEDDAKAKANI") == "5",
              f"table in gnt-vja order: {[(r[0], r[1]) for r in tb]}")

        print("\n--- 7. Clean up: reset AP-16-5001 and AP-16-1234 ---")
        reset_bus(page)
        page.reload()
        wait_js(page, "return busState && busState.bus_id === 'AP-16-1234'", timeout=30)
        reset_bus(page)
        check(True, "both buses reset")
        check(not errors, f"no page errors: {errors}")
        browser.close()
    httpd.shutdown()

    passed = sum(1 for ok, _ in results if ok)
    print(f"\nRESULT: {passed}/{len(results)} checks passed")
    for ok, label in results:
        if not ok:
            print(f"  FAILED: {label}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
