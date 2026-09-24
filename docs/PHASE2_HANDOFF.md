# TravelloBus: Phase 2 handoff (work done on 24 Sep 2026)

Paste this file into a new Claude chat as context. It records everything done in the Phase 2 session: what was diagnosed, what changed, how it was tested, how it's deployed, and what's still open.

---

## 1. Project at a glance

- **What it is:** Smart India Hackathon 2026 prototype (team CityCoders, PS 26205, Transportation & Logistics). The core idea is that **the ETM ticket is the sensor**: occupancy = passengers whose ticketed destination is still ahead of the bus. No cameras, no new hardware.
- **Repo:** https://github.com/citycoders365/prototype2, branch `master`.
- **Live frontend (Vercel, project `travellobus-app`):**
  - Passenger PWA + admin: https://travellobus-app.vercel.app/
  - ETM simulator: https://travellobus-app.vercel.app/etm.html
- **Live backend (Render free tier):** https://prototype2-qqw6.onrender.com. Health check: `GET /api/health` → `{"ok": true, "db": true, "version": "phase2-stage3"}`
  - Render settings: root directory `backend`, start command `uvicorn main:app --host 0.0.0.0 --port $PORT`, Python 3.12.8 (`.python-version`), env vars `SUPABASE_URL`, `SUPABASE_KEY`.
- **Database:** Supabase Postgres, project ref `aohtgcjyhocbzvxnmdwk`, used through the `supabase` Python client with the publishable key.
- **Files that matter:**
  - `backend/main.py`: FastAPI backend
  - `etm.html`: ETM simulator (vanilla JS)
  - `index.html`: passenger PWA + admin console (vanilla JS, about 2,900 lines)
  - `tests/`: all test scripts (see section 7)
- **Git tags:**

  | Tag | Commit | Meaning |
  |---|---|---|
  | `stable-0924` | `6287f73` | Original version, before this work |
  | `phase1-done` | `adec7bb` | Phase 1: hardcoded values / overclaiming labels removed (done before this session) |
  | `phase2-stage1` | `da118cb` | Backend rewrite |
  | `phase2-stage2` | `53b690c` | ETM rewrite |
  | `phase2-stage3` | `72d9158` | Passenger PWA rewrite (**current HEAD, live**) |

- **Author's environment:** Windows + PowerShell, project in a OneDrive folder. `py` launcher (Python 3.14 locally).

---

## 2. Route, bus and fare facts (used everywhere; don't change without checking all three files)

- **Stops, vja-gnt direction, in order:** `VIJAYAWADA PNBS, TADEPALLI, MANGALAGIRI, NAMBURU, PEDDAKAKANI, GUNTUR RTC`. The **gnt-vja** direction is the same list reversed.
- A **stop index** is the position along **that bus's own direction** (0 = its first stop). For gnt-vja buses, index 0 = GUNTUR RTC.
- **Buses** (same ids in `etm.html`, `index.html`, `backend/main.py`):

  | id | plate | direction |
  |---|---|---|
  | AP-16-1234 | AP16Z-4022 | vja-gnt |
  | AP-16-4023 | AP16Z-4023 | vja-gnt |
  | AP-16-4024 | AP16Z-4024 | vja-gnt |
  | AP-16-4025 | AP16Z-4025 | vja-gnt |
  | AP-16-4026 | AP16Z-4026 | vja-gnt |
  | AP-16-5001 | AP16Z-5001 | gnt-vja |
  | AP-16-5002 | AP16Z-5002 | gnt-vja |

- **Seat capacity:** 50 by default.
- **Fare:** flat ₹35 per passenger for `full`. `zero_fare` (Stree Shakti) and `pass` are ₹0 but **still count as passengers**. Fare is always computed by the server: 35 × `ticket_count` for full.
- **Stop timing offsets** (index.html `routeStopsTemplate`): 0, 15, 30, 45, 55, 70 minutes along vja-gnt. For gnt-vja, gaps are the absolute offset differences, i.e. 15, 10, 15, 15, 15 minutes.

---

## 3. Database (Supabase): already migrated, do NOT recreate tables

- `trips(id uuid, bus_id text, seat_capacity int default 50, is_legacy bool default false, start_time timestamptz)`
- `trip_snapshots(trip_id, stop_index, onboard_count, timestamp)`, primary key `(trip_id, stop_index)`. Upsert only.
- `ticket_events`:
  - old columns: `id uuid, bus_id, origin, destination, ticket_count, timestamp`
  - plus `trip_id uuid, ticket_type text default 'full', origin_index int default 0, destination_index int default 1, client_event_id uuid UNIQUE, fare numeric NOT NULL default 0`
  - CHECKs: `ticket_type IN ('full','zero_fare','pass')`, `destination_index > origin_index`, `ticket_count >= 1`
- `live_bus_state`:
  - primary key `bus_id`
  - old columns `total_capacity, occupied_seats, last_updated` (unused now)
  - plus `current_trip_id uuid, current_stop_index int default 0, seat_capacity int default 50, lat, lng, speed, last_stop_name`
- `gps_events(id, bus_id, trip_id, lat, lng, speed, timestamp)`: exists, currently empty, not used yet.
- Views: `depot_totals_view`, `recent_active_trips_view`. Not used by the app yet (see Stage 4).
- Tickets from before Phase 2 have `trip_id = NULL` or belong to legacy trips. **Only tickets on a bus's current trip count.** Old rows are never deleted.
- **Stray row:** `live_bus_state` has a row with `bus_id = 'AP16Z-4022'` from an earlier migration. It's unused. Ignore it; don't delete it.
- DDL can't be run from code. Any SQL goes in `sql/phase2.sql` for the owner to run in the Supabase SQL editor.

---

## 4. Owner's working rules (follow these in future chats)

1. Work in **stages**. At the end of each stage, stop, report, and wait for "OK".
2. **Targeted edits only.** Never rewrite whole files; keep the existing visual design.
3. **No scratch files in the project root.** Tests go in `tests/`, SQL in `sql/`.
4. **Never commit or push without the owner's OK.** When approved: commit, push, and tag (`phase2-stageN`, …).
5. **Never claim something works unless you ran it**; otherwise say "untested".
6. Backend endpoints use `def`, not `async def`. Re-raise `HTTPException` before any generic `except`. Generate timestamps in Python (UTC ISO), never the string `"now()"`.
7. **No counters anywhere.** Occupancy is always computed from ticket rows. Never read-modify-write `occupied_seats`.
8. **Version string:** bump `VERSION` in `backend/main.py` at every stage. After a push, poll `/api/health` every 10s (up to 5 minutes) until the new version shows, then run the tests.
9. If the code contradicts the prompt (stop names, bus ids, field names), ask the owner rather than guessing.

---

## 5. Stage 0: diagnosis (why "only the first ticket updates" on non-4022 buses)

`tests/diagnose.py` was run against Render. **The old backend counted correctly** (+3 on all 7 buses), so the bug was not lost updates. Real causes found:

- **H: server handled one request at a time (main cause).** Endpoints were `async def` but called the synchronous supabase client, which blocks the event loop.
  - Measured: 7 parallel `bus_state` requests took 2.4s wall time, i.e. fully serialized.
  - The PWA polled each of the 7 buses separately every 3s, plus the ETM poll. With one viewer the server was about 93% busy; a second device pushed it past 100% and the backlog grew without limit. Tickets waited 10–15s behind it.
- **I: PWA poll bug.** `responses.forEach(async …)` meant the list rendered before the new data arrived (always one poll behind), the stale banner never fired, and overlapping polls let older responses overwrite newer counts.
- **J: ETM count reverted.** The ETM added tickets to its total locally, then a poll requested *before* the insert overwrote it. Symptom: "only the first ticket updates, the rest appear later".
- **D: ETM fire-and-forget.** One `fetch`, no retry, no check of the response status. A failure lost the ticket silently.
- **G: `etmNewEvent` localStorage shortcut.** Made the same browser look updated while other devices weren't. It also double-counted drop-offs.
- **K: counts included every ticket ever issued** (no trip filter). AP-16-1234 showed 71/60.
- **Rejected causes:** A (read-modify-write counter; it didn't exist), B (the PWA did poll all buses), C (the poll interval was already 3s), F (no bus/stop mismatches).
- **E (Render cold start):** real by design (free tier sleeps after about 15 minutes idle), but not measured because the server was warm.

---

## 6. What was built

### Stage 1: `backend/main.py` (tag `phase2-stage1`)

Restructured (every endpoint changed), keeping the app, CORS and config skeleton.

- **Helpers:**
  - `STOPS`, `DIRECTION_STOPS`, `BUS_DIRECTION`, `stops_for(bus_id)`, `stop_index(bus_id, name)`.
  - Supabase access through `db(build)`: a **pool of clients** (LIFO queue, 4 warmed in the background at startup), **retries up to 2 times on connection errors only** with a fresh client, never retries `APIError` (e.g. 23505).
  - Middleware logs every request and adds headers **`X-Response-Time-ms`** and **`X-DB-Calls`** (exposed through CORS).
- **Endpoints** (all `def`):
  - `GET /api/health`: 1 DB call. Returns `{"ok": true, "db": true, "version": VERSION}`, or HTTP 503 `{"ok": false, "db": false, …}` if the DB fails.
  - `POST /api/issue_ticket`: 3 DB calls: state row, insert, trip tickets.
    - Body: `bus_id`, `origin`/`destination` (names) **or** `origin_index`/`destination_index`, `ticket_count` (default 1), `ticket_type` (default `full`), `client_event_id` (UUID, optional), `fare` (accepted but ignored).
    - If both a name and an index are sent they must agree, otherwise 422.
    - 422 with a clear message for: unknown bus, unknown stop, destination not after origin, `ticket_count < 1`, bad `ticket_type`, `client_event_id` not a UUID.
    - Creates a trip (and the `live_bus_state` row) if the bus has none.
    - Inserts one row with `trip_id` = current trip and a server-computed fare.
    - **Duplicate `client_event_id`** (Postgres 23505) → 200 `{"duplicate": true}`. No pre-check query. If the client sent no id, the server generates one, so its own retries can't double-insert.
    - Returns the full bus state (onboard etc.) plus `status, duplicate, message, client_event_id, ticket_type, fare`.
  - `GET /api/bus_state/{bus_id}`: 2 DB calls. Unknown bus → 422. A bus with no trip → zeros (200). The response fields are listed below.
  - `GET /api/bus_states?ids=A,B,…` (all 7 if omitted): **2 DB calls for any number of buses**, using `.in_()`. Returns `{"buses": {bus_id: state}, "unknown": [...], "server_time"}`.
  - `POST /api/advance_stop/{bus_id}`: 4 DB calls.
    - Upserts a `trip_snapshots` row (current index, onboard) **before** moving, then moves +1.
    - The update is conditional (`current_stop_index = idx`), so two simultaneous calls give **409** instead of skipping a stop.
    - At the last stop: 200, `moved: false`, unchanged.
    - Returns `moved`, `onboard_departing` + state.
  - `POST /api/reset_trip/{bus_id}`: 2 DB calls. Optional `seat_capacity` (JSON body or `?seat_capacity=`, 1–500, default 50). Creates a new trip, sets it current at index 0, upserts the `live_bus_state` row. Never deletes tickets.
  - `GET /api/dropoffs/{bus_id}`: legacy endpoint, kept; returns the forecast in the old format.
- **State response fields:**
  - `bus_id, direction, trip_id, seat_capacity`
  - `onboard, seated, empty, standing, occupancy_pct`
  - `drop_off_forecast` = `[{stop, stop_index, count}]`: stops ahead only, count > 0, sum = onboard (an error is logged if not)
  - `current_stop_index, current_stop_name, next_stop_name`
  - `stops` (this bus's travel order), `last_updated, last_stop_name, lat, lng, speed, server_time`
  - Legacy compatibility fields: `total_capacity`, `occupied_seats` (= onboard), `dropoffs` (`[{stop, count, eta: "N/A"}]`)
- **Occupancy rule:** onboard = Σ `ticket_count` on the current trip where `destination_index > current_stop_index`. A ticket whose origin is already behind the bus (late ticket) still counts if its destination is ahead.

### Stage 2: `etm.html` (tag `phase2-stage2`)

- **Warm-up:** calls `/api/health` on page load. The badge shows "● Connecting…" → "● Connected to cloud" (or "● Offline, retrying"); the status strip shows "Connecting…" → "Ready".
- **Payload:** sends `bus_id, origin, destination, origin_index, destination_index` (indices along **the bus's direction**), `ticket_count, ticket_type, client_event_id`. Uses `crypto.randomUUID()`, with a Math.random UUID v4 fallback for pages opened as a local file.
- **FN key:** cycles Full → Stree Shakti ₹0 → Pass → Full. The screen shows `TYPE: …`, and it resets to Full after every ticket.
- **Durable queue** (localStorage key `etmTicketQueue`):
  - A ticket is saved **before** it's sent, and sent immediately.
  - **Deviation approved by the owner:** up to **5 requests in flight at once**, dispatched in queue order, never two requests for the same ticket. Strictly one-at-a-time took 6.9s for 5 rapid tickets; this takes about 2s.
  - Removed only on a 200 (including `duplicate`).
  - Network errors, timeouts, 5xx, 408 and 429 are retried with backoff 1s, 2s, 5s, then every 10s. Other 4xx → dropped with a red log line and the reason; the queue is never blocked.
  - Flushes on `visibilitychange` (visible), `focus`, `online` and page load.
- **Feedback strip under the screen:** "Sending…" → "✓ Synced — N onboard" (N from the `issue_ticket` response, using the freshest state) → "Waking server…" if not confirmed within 3s. Shows "⟳ N pending" when tickets are queued.
- **CORS preflight warm-up:** after health answers, and every 5 minutes, it sends an `OPTIONS` request to `/api/issue_ticket` so the browser caches the preflight (`Access-Control-Max-Age` 600s). The first ticket then skips an extra round trip. The OPTIONS itself gets a harmless 405 in the Render logs.
- **Numbers from the backend only:** the `etmNewEvent` shortcut is removed. The ETM polls `/api/bus_state` for the selected bus every 3s **at every step, including bus selection** (default AP-16-1234); polling pauses while the tab is hidden. Responses older than the shown state are ignored (compared by `server_time`).
  - "Passengers onboard" (renamed from "Total Passengers") comes from the backend.
  - The drop-off table follows the bus's travel order, with statuses Passed / Bus here / Ahead.
  - **"Est. revenue (this trip)"** is summed on the ETM from fares the server confirmed, per trip id (localStorage `etmRevenueByTrip`), because the backend doesn't return revenue yet.
- **Demo controls** ("Demo controls (simulates GPS feed)", collapsed, under the keypad): "Advance to next stop ▶" with the current and next stop, and "Reset trip" (asks for confirmation). Both are disabled while a request is running.
- Boarding stop defaults to the **bus's current stop**. All fetches use `cache: 'no-store'`.

### Stage 3: `index.html` (tag `phase2-stage3`)

- **Warm-up:** `/api/health` is called during the splash screen.
- **Removed:** the `etmNewEvent` listener, all local occupancy changes, sample occupancy values in `busData` (now `null` → shown as "—"), the old `pollBackend`, and the clock-based `initLiveTimings`/`updateTimings`.
- **One poller** (`pollNow`, every 3s, `POLL_MS`), polling whatever is on screen:
  - Bus list: **one** `/api/bus_states` request for the buses shown (the current search direction).
  - Admin list: `/api/bus_states` for all 7. This also feeds the admin live overlay.
  - Details page: `/api/bus_state/{bus}`.
  - One request per key at a time; out-of-order responses are dropped by `server_time`.
  - Pauses while hidden; polls immediately on visible/focus/online; `navigate()` also polls immediately.
- **Bus list card:**
  - Badge `onboard/capacity`: green under 60%, amber 60–99%, red "Full" at or over capacity, "—" with no data. Never a standing count.
  - Subtitle "At <current stop>".
- **Details page** (`renderTracking(bus)`):
  - Occupied / Empty / Standing from onboard and capacity. The percentage label shows the real value (e.g. 133%); the bar is capped at full width.
  - Opening a bus with no data shows "—", never the previous bus's numbers.
- **Drop-off panel and admin overlay:** use `drop_off_forecast` (ahead-only). "Current onboard" = onboard. "After next stop" = onboard − count at `current_stop_index + 1`. "No passengers yet." when empty, "Waiting for live data…" before the first reply.
- **Timeline:** built from the backend `stops` and `current_stop_index`, not the clock.
  - Passed stops: "Departed". Current stop: "Now". Upcoming: "ETA HH:MM Scheduled" = now + (offset[j] − offset[current]).
  - "Next Stop ETA" = e.g. "15 min (scheduled)", or "At last stop".
  - gnt-vja buses start at GUNTUR RTC, and the route reads "Guntur → Vijayawada".
- **Stale banner:** "⚠ Data may be outdated, last update HH:MM" after **15s** without a successful update (`STALE_MS`), checked every second.
- **Kept from Phase 1:** `no-store`, speed "— Simulated", "Sample" tags on the admin totals.

### After Stage 3: header logo (commit after `phase2-stage3`, no tag)

- The Bus Details header pill now shows the TravelloBus bus-and-arrow icon from `assets/travellobus-icon.png` (192×192 PNG, white margins trimmed).
- It used to copy the wide splash-screen logo, which was unreadable at that size. The copying code was removed.
- Logo height 28px → 36px, in both the `.rt-logo-pill img` CSS and the `<img>` tag's inline style.
- Frontend only; backend `VERSION` unchanged.

---

## 7. Tests (all in `tests/`, Python)

Setup on Windows:

```bash
py -m pip install requests playwright
```

The browser tests use the **installed Microsoft Edge** (`channel="msedge"`), so no browser download is needed.

| Script | What it does | Side effects |
|---|---|---|
| `tests/diagnose.py` | Stage 0: cold-start time, 3 parallel tickets per bus with the old payload, load check | Inserts tickets |
| `tests/test_phase2_backend.py` | 46 backend checks: reset all 7, acceptance scenario, advances, late ticket, duplicate, 6 kinds of 422, capacity 3 (133%), concurrency (5 parallel tickets on every bus), batch timing, final reset. Prints client time, server time, DB calls. | Resets all buses, inserts tickets, ends with all 7 reset to capacity 50 |
| `tests/test_etm_browser.py` | 35 checks in Edge: warm-up, polling on bus selection, UUID fallback, FN types, payload, sync timing, demo controls, network-down queue surviving a reload, 503 retry, 422 drop without blocking, 5 rapid tickets on AP-16-5001 | Resets AP-16-1234 and AP-16-5001 (again at the end) |
| `tests/test_pwa_browser.py` | 33 checks in Edge: warm-up, one batch request per poll, badge colours, acceptance scenario on the details page, advances, timeline, paused while hidden, stale banner, 133% capacity, gnt-vja order, admin list and overlay | Resets all buses at the end |

Run with `py tests\<script>.py`. Options:
- `$env:BASE = "http://localhost:8000"` points the backend tests at a local server.
- `$env:EXPECT_VERSION = "phase2-stageN"` makes the backend test abort if the wrong version is deployed.
- `$env:HEADED = "1"` shows the browser.
- If the console shows encoding errors, set `$env:PYTHONIOENCODING = "utf-8"`.

**Last results (live, after the final deploy):** backend 46/46, ETM 35/35, PWA 33/33.

**Running the backend locally:** `backend/requirements.txt` pins `fastapi==0.109.2` / `pydantic==2.6.1`, which won't install on Python 3.14. For local runs, use a separate venv with the latest `fastapi uvicorn supabase`; the code is compatible with both. Then run `uvicorn main:app --port 8765` from `backend/`.

---

## 8. Measured performance (server warm)

| What | Result |
|---|---|
| `issue_ticket` server time | median about 470ms (max about 770ms); 3 DB calls |
| `bus_state` server time | about 310ms; 2 DB calls |
| `bus_states`, all 7 buses | about 350ms; 2 DB calls |
| `advance_stop` server time | about 650ms; 4 DB calls |
| `reset_trip` server time | about 320ms; 2 DB calls |
| Each Supabase call from Render | about 150–200ms (occasional spikes up to about 1.2s) |
| Network, laptop ↔ Render | about 0.3s |
| ETM: ENT → "✓ Synced" | 1.1–2.0s |
| Phone (2nd browser) shows 1 ticket | 2.2–3.8s |
| Phone shows 3 rapid tickets | about 3s |
| 5 rapid tickets on one bus | all counted exactly once, about 2s |

---

## 9. Known limitations / still simulated

- **Admin totals** (₹12,450, 458 tickets) are sample data, tagged "Sample". Stage 4 would make them real.
- **Simulated:** the admin map animation (bus moving along a fixed path), "On-Time %" figures, speed ("— Simulated").
- **No real GPS feed yet:** the ETM's "Advance to next stop" button stands in for GPS; `gps_events` is empty.
- **Render free tier** sleeps after about 15 minutes idle (cold start 30–60s). **Supabase free** projects pause after a period of inactivity. See section 10, item 1.
- **Browsers tested:** Edge (Chromium) only. Safari on iOS and real mobile networks are untested.
- **The demo endpoints have no authentication:** anyone can reset or advance. Acceptable for a prototype.
- **Outdated docs:** `DEPLOY_GUIDE.md` refers to old filenames (`citycoders.html`, Netlify). Older files in the project root (`out.txt`, `out2.txt`, `test_dropoffs_table.py`, `test_supabase.py`, `apply_schema_pg.py`, `yolov8n.pt`, `seed_buses.py`, `serve_frontend.py`) are tracked in git from before this session and were not touched.

---

## 10. Open items / next steps

1. **Keep the demo awake through October (owner to set up; not done yet):**
   - Create a free **UptimeRobot** (or cron-job.org) HTTP(s) monitor on `https://prototype2-qqw6.onrender.com/api/health` every **5 minutes**, with email alerts. This keeps Render awake **and** keeps Supabase active, because health runs a DB query.
   - Check Render free hours: 24/7 in October = 744 of 750 per month, so suspend any other free Render services on the account.
   - Alternative: Render Starter plan (about $7/month; check current pricing) for October.
   - Optional: a nightly 3 AM IST POST to `/api/reset_trip/{id}` for each bus (cron-job.org), so every day starts clean.
   - Optional backup: a GitHub Actions scheduled pinger (can be delayed; backup only; needs OK to push).
2. **Stage 4 (optional, not started):** `GET /api/depot_summary` from `depot_totals_view`, to replace the "Sample" admin totals. If the view's `zero_fare_value` must match the flat ₹35, write a `CREATE OR REPLACE VIEW` into `sql/phase2.sql` for the owner to run. (The view currently returns e.g. `total_tickets, total_revenue, zero_fare_count, zero_fare_value, pass_count`.)
3. **Optional speed-up:** cache each bus's current trip (trip_id, stop index, capacity) in backend memory, updated by `bus_state`/advance/reset, to cut `issue_ticket` from 3 to 2 DB calls (about 200ms faster). Safe only because Render runs a single instance.
4. **PPT:**
   - The updated deck is `SIH2026-IDEA-CityCoders-TravelloBus-v2.pptx` (Downloads on the friend's PC; **copy it over**). The original is unchanged.
   - Still to do:
     - Slide 1 Team ID ("----to be filled----").
     - Slide 6 demo-video link (update after re-recording).
     - Old screenshots: slide 3 shows the old ETM ("Live Audit Plugin"); slide 5 shows the old admin console with sample numbers. Replace them with fresh screenshots of the live site at the same size and position.
5. **Demo video:**
   - The old Drive video (file named `pro.mp3`; it's actually a video) predates this work and shows the old UI. **Re-record** using the script in section 12. If you keep any Drive file, rename it, e.g. `TravelloBus-Demo-CityCoders.mp4`.
6. **Before any demo:**
   - Open the ETM 2 minutes early and wait for "● Connected to cloud".
   - Reset the buses you'll use (Demo controls → Reset trip).
   - Do one two-device check: laptop ETM + phone in a private tab.

---

## 11. PPT changes made (v2 deck)

Text only; formatting kept; checked in PowerPoint with no overflow.

- **Slide 2:** "Transparent by design" now mentions Stree Shakti zero-fare tickets being logged for audit.
- **Slide 3:**
  - Prototype = "Passenger PWA, ETM simulator and depot view with live seat counts, running on cloud".
  - Validation = "automated tests fire 5 tickets at once on each of 7 buses; every ticket is counted exactly once".
  - Integration mentions tickets arriving at the RTC server in real time.
- **Slide 4:**
  - Feasibility: "ETM tickets already sync to RTC servers in real time, and buses carry AIS-140 GPS" (replaced the "bus locations are published publicly" claim).
  - Phase 1 now includes "validated against manual headcounts".
  - New risk: pass holders / late tickets, with the one-key ₹0 "Pass" fix.
  - Revenue model: APSRTC corridor pilot → depot-wide → other state RTCs.
- **Slide 5:**
  - "Fiscal accountability (Stree Shakti)" moved to first place.
  - Tier-2 claim softened ("where live crowding information isn't available today").
  - Conductors: "no new device; one extra key for pass holders".
- **Slide 6:** removed the vague IEEE reference.

---

## 12. Demo video script (about 1:45; record with both screens ready)

**Setup:**
- ETM (left): "Connected to cloud", on bus selection, AP16Z-4022 reset, Demo controls open.
- Phone (right): signed in as Passenger, Search Buses done (VIJAYAWADA PNBS → GUNTUR RTC), list shows AP16Z-4022 0/50.

| Time | On screen / keys | Narration |
|---|---|---|
| 0:00–0:10 | Both screens | "Commuters never know how full a bus is until it arrives. And the RTC has no live view either. We're CityCoders, and this is TravelloBus." |
| 0:10–0:25 | Both screens | "Our idea: the ticket is the sensor. Every ETM ticket says where a passenger gets on and off, and it already reaches the RTC in real time. So passengers on board is simply the tickets whose stop is still ahead. No cameras, no new hardware." |
| 0:25–0:45 | ETM: **C → C → ▼▼▼▼ → C → 3 → ENT**. Wait for phone 3/50, tap AP16Z-4022 | "The conductor prints three tickets to Guntur. It's synced in about a second, and the passenger's phone shows three on board." |
| 0:45–1:10 | ETM: **C → ▼ → C → FN → ENT**, then **C → C → FN → FN → ENT**. Phone: 5 occupied / 45 empty, open Drop-Off tab | "A Stree Shakti free ticket and a bus pass. Zero rupees each, but real passengers, so both are counted. Revenue stays at 105 rupees, so every zero-fare trip is auditable. And the drop-off tab shows exactly how many get off at each stop." |
| 1:10–1:30 | ETM: **Advance to next stop ▶**. Phone: 4, TADEPALLI "Now" | "In real use, GPS moves the bus; here, this button stands in for it. At Tadepalli one passenger gets off, and the count drops to four automatically." |
| 1:30–1:45 | Team / impact slide | "No new hardware, just data the RTC already has. Passengers choose a less crowded bus, and the RTC sees real demand and proof of every Stree Shakti trip. Next step: a ten-bus pilot on the Vijayawada–Guntur corridor. Thank you." |

**ETM key meanings:**
- **C** = OK / next step (bus → boarding stop → destination → quantity).
- **▼/▲** = change the selection. A digit sets the quantity. **ENT** = print. **FN** = ticket type.
- After each print the ETM returns to boarding-stop selection, with the bus's current stop preselected.

---

## 13. Jury Q&A prep (short answers)

- **Where does the data come from?** APSRTC ETMs already sync tickets to the RTC server in real time. We need read-only access to that stream plus the AIS-140 GPS feed. Nothing is installed on ETMs, nothing changes for conductors, and no passenger identity is stored. The only dependency is a data-sharing agreement.
- **Accuracy?** It's arithmetic, not prediction. It can drift in three known ways, each handled:
  - Pass holders: a one-key ₹0 Pass record.
  - Early alighting: the count self-corrects at the ticketed stop.
  - Late tickets: reconciled by stop position; the app shows "last updated".
  - Best evidence would be a field test: ride N trips, count by hand, and quote "within ±X". **Don't invent a number.**
- **No ticket issued?** That's fare evasion that's invisible today. Low ticket counts on a route become an inspection flag.
- **Why not cameras or AI?** Hardware, maintenance, privacy, and poor performance in crowded buses. We use data RTC already has. AI is only an optional later layer (boarding prediction).
- **Chalo / Google Maps / APSRTC app?** They mostly show *where* the bus is; we show *how full* it is and drop-offs per stop. We're a data layer that can plug into APSRTC's app. (Check what each app actually shows before claiming.)
- **Low bus frequency?** Passengers can still choose this bus or the next, but the main value is for the RTC: near-empty services, demand, and Stree Shakti audit.
- **Is the demo real?** The backend, database and app are real and live. The ETM is a simulator, and the Advance button stands in for GPS. Say this honestly.
- **Network drops?** Tickets queue on the device and resend; duplicates are rejected, so nothing is lost or counted twice. The app shows a stale warning after 15s.
- **Scale?** Each bus is an independent calculation, and one request serves many buses. Production moves to RTC or government cloud.
- **Business model?** The RTC is the customer: corridor pilot → depot-wide → other state RTCs.
- **Tip:** acknowledge a weakness first, then give the fix. Never claim something you haven't verified.
