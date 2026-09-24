from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from supabase import create_client, Client
from postgrest.exceptions import APIError
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional
import httpx
import logging
import os
import queue
import threading
import time
import uuid

VERSION = "phase2-stage3"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("travellobus")

# Initialize FastAPI app
app = FastAPI(title="TravelloBus Backend PoC")

# Allow CORS for local HTML file testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Response-Time-ms", "X-DB-Calls"],
)

# Supabase config
# Ensure SUPABASE_URL and SUPABASE_KEY are set in your environment
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://aohtgcjyhocbzvxnmdwk.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_vBoZvNOIgcSfeYcp4PjnHQ_2pcnqNVG")

# ==========================================
#  ROUTE + BUS FACTS
# ==========================================
STOPS = ["VIJAYAWADA PNBS", "TADEPALLI", "MANGALAGIRI", "NAMBURU", "PEDDAKAKANI", "GUNTUR RTC"]
DIRECTION_STOPS = {"vja-gnt": STOPS, "gnt-vja": list(reversed(STOPS))}
BUS_DIRECTION = {
    "AP-16-1234": "vja-gnt",  # plate AP16Z-4022
    "AP-16-4023": "vja-gnt",
    "AP-16-4024": "vja-gnt",
    "AP-16-4025": "vja-gnt",
    "AP-16-4026": "vja-gnt",
    "AP-16-5001": "gnt-vja",
    "AP-16-5002": "gnt-vja",
}
DEFAULT_CAPACITY = 50
FARE_PER_PASSENGER = {"full": 35, "zero_fare": 0, "pass": 0}
STATE_COLS = "bus_id,current_trip_id,current_stop_index,seat_capacity,last_stop_name,last_updated,lat,lng,speed"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stops_for(bus_id: str) -> list:
    """Ordered stops in THIS bus's travel direction (index 0 = its first stop)."""
    direction = BUS_DIRECTION.get(bus_id)
    if direction is None:
        raise HTTPException(status_code=422, detail=f"Unknown bus '{bus_id}'. Known buses: {', '.join(BUS_DIRECTION)}")
    return DIRECTION_STOPS[direction]


def stop_index(bus_id: str, name: str) -> Optional[int]:
    key = (name or "").strip().upper()
    stops = stops_for(bus_id)
    return stops.index(key) if key in stops else None


# ==========================================
#  SUPABASE ACCESS (client pool + retry + per-request call count)
# ==========================================
# Each client is used by one request at a time; LIFO keeps the warmest connections in use.
_pool: "queue.LifoQueue[Client]" = queue.LifoQueue()
_db_calls: ContextVar[Optional[list]] = ContextVar("db_calls", default=None)
POOL_WARM_SIZE = 4


def _borrow() -> Client:
    try:
        return _pool.get_nowait()
    except queue.Empty:
        return create_client(SUPABASE_URL, SUPABASE_KEY)


def _is_connection_error(e: Exception) -> bool:
    if isinstance(e, APIError):
        return False
    if isinstance(e, (httpx.TransportError, ConnectionError, TimeoutError)):
        return True
    return (type(e).__module__ or "").startswith(("httpcore", "h2", "h11", "ssl"))


def db(build):
    """Run one Supabase query. `build(client)` returns a query builder; we execute it.
    Rebuilds the client and retries (max 2) on connection errors only. Never retries APIError (e.g. 23505)."""
    for attempt in range(3):
        box = _db_calls.get()
        if box is not None:
            box[0] += 1
        client = _borrow()
        broken = False
        try:
            return build(client).execute()
        except Exception as e:
            broken = _is_connection_error(e)  # drop this client; the retry builds a fresh one
            if attempt < 2 and broken:
                log.warning("Supabase connection error (attempt %d), rebuilding client: %r", attempt + 1, e)
                time.sleep(0.1 * (attempt + 1))
                continue
            raise
        finally:
            if not broken:
                _pool.put(client)


@app.on_event("startup")
def warm_pool():
    """Open a few Supabase connections in the background so the first requests after a wake-up are fast."""
    def warm_one():
        try:
            db(lambda c: c.table("live_bus_state").select("bus_id").limit(1))
        except Exception as e:
            log.warning("Pool warm-up failed: %r", e)

    def run():
        # Run concurrently so each call borrows (and then returns) its own client.
        threads = [threading.Thread(target=warm_one) for _ in range(POOL_WARM_SIZE)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        log.info("Supabase pool warmed: %d clients", _pool.qsize())

    threading.Thread(target=run, daemon=True).start()


def fetch_state_row(bus_id: str) -> Optional[dict]:
    res = db(lambda c: c.table("live_bus_state").select(STATE_COLS).eq("bus_id", bus_id).limit(1))
    return res.data[0] if res.data else None


def fetch_trip_tickets(trip_id: str, after_index: int) -> list:
    """Tickets of one trip whose destination is still ahead of `after_index`."""
    res = db(lambda c: c.table("ticket_events")
             .select("destination_index,ticket_count")
             .eq("trip_id", trip_id)
             .gt("destination_index", after_index))
    return res.data or []


def ensure_trip(bus_id: str, row: Optional[dict]) -> dict:
    """Return a state row with a current trip, creating the trip (and the live_bus_state row) if missing."""
    if row and row.get("current_trip_id"):
        return row
    cap = (row or {}).get("seat_capacity") or DEFAULT_CAPACITY
    trip = db(lambda c: c.table("trips").insert({
        "bus_id": bus_id, "seat_capacity": cap, "is_legacy": False, "start_time": now_iso()}))
    fields = {
        "current_trip_id": trip.data[0]["id"],
        "current_stop_index": 0,
        "seat_capacity": cap,
        "last_stop_name": stops_for(bus_id)[0],
        "last_updated": now_iso(),
    }
    try:
        if row is None:
            res = db(lambda c: c.table("live_bus_state").insert({"bus_id": bus_id, **fields}))
        else:
            # Only claim the slot if nobody else set a trip meanwhile.
            res = db(lambda c: c.table("live_bus_state").update(fields)
                     .eq("bus_id", bus_id).is_("current_trip_id", "null"))
    except APIError as e:
        if getattr(e, "code", None) != "23505":
            raise
        res = None
    if res is not None and res.data:
        return {**(row or {}), **res.data[0]}
    fresh = fetch_state_row(bus_id)  # lost a race: use whatever trip won
    if not fresh or not fresh.get("current_trip_id"):
        raise RuntimeError(f"Could not create a trip for {bus_id}")
    return fresh


def compute_state(bus_id: str, row: Optional[dict], tickets: list) -> dict:
    """Occupancy for the current trip, computed ONLY from ticket rows (no counters)."""
    stops = stops_for(bus_id)
    last = len(stops) - 1
    row = row or {}
    idx = min(max(int(row.get("current_stop_index") or 0), 0), last)
    cap = int(row.get("seat_capacity") or DEFAULT_CAPACITY)

    counts = [0] * len(stops)
    onboard = 0
    for t in tickets:
        d, n = t.get("destination_index"), t.get("ticket_count") or 0
        if d is None or d <= idx:
            continue
        onboard += n
        if d <= last:
            counts[d] += n
    forecast = [{"stop": stops[i], "stop_index": i, "count": counts[i]}
                for i in range(idx + 1, last + 1) if counts[i] > 0]
    if sum(f["count"] for f in forecast) != onboard:
        log.error("Forecast sum %d != onboard %d for %s (trip %s)",
                  sum(f["count"] for f in forecast), onboard, bus_id, row.get("current_trip_id"))

    return {
        "bus_id": bus_id,
        "direction": BUS_DIRECTION[bus_id],
        "trip_id": row.get("current_trip_id"),
        "seat_capacity": cap,
        "onboard": onboard,
        "seated": min(onboard, cap),
        "empty": max(0, cap - onboard),
        "standing": max(0, onboard - cap),
        "occupancy_pct": round(onboard / cap * 100) if cap else 0,
        "drop_off_forecast": forecast,
        "current_stop_index": idx,
        "current_stop_name": stops[idx],
        "next_stop_name": stops[idx + 1] if idx < last else None,
        "stops": stops,
        "last_updated": row.get("last_updated"),
        "last_stop_name": row.get("last_stop_name"),
        "lat": row.get("lat"),
        "lng": row.get("lng"),
        "speed": row.get("speed"),
        "server_time": now_iso(),
        # Compatibility fields for the pre-phase-2 frontend
        "total_capacity": cap,
        "occupied_seats": onboard,
        "dropoffs": [{"stop": f["stop"], "count": f["count"], "eta": "N/A"} for f in forecast],
    }


def server_error(where: str, e: Exception) -> HTTPException:
    log.exception("Error in %s: %r", where, e)
    return HTTPException(status_code=500, detail="Internal server error")


# ==========================================
#  RESPONSE-TIME LOGGING
# ==========================================
@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    box = [0]
    token = _db_calls.set(box)
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        _db_calls.reset(token)
    ms = (time.perf_counter() - t0) * 1000
    response.headers["X-Response-Time-ms"] = f"{ms:.0f}"
    response.headers["X-DB-Calls"] = str(box[0])
    log.info("%s %s -> %s in %.0f ms (db calls: %d)",
             request.method, request.url.path, response.status_code, ms, box[0])
    return response


# ==========================================
#  ENDPOINTS
# ==========================================
@app.get("/api/health")
def health():
    try:
        db(lambda c: c.table("live_bus_state").select("bus_id").limit(1))
        return {"ok": True, "db": True, "version": VERSION}
    except Exception as e:
        log.exception("Health check DB error: %r", e)
        return JSONResponse(status_code=503, content={"ok": False, "db": False, "version": VERSION})


# Define request schemas
class TicketEvent(BaseModel):
    bus_id: str
    origin: Optional[str] = None
    destination: Optional[str] = None
    origin_index: Optional[int] = None
    destination_index: Optional[int] = None
    ticket_count: int = 1
    ticket_type: str = "full"
    client_event_id: Optional[str] = None
    fare: Optional[float] = None  # accepted but ignored: fare is decided server-side


def resolve_stop(bus_id: str, name: Optional[str], index: Optional[int], label: str) -> int:
    stops = stops_for(bus_id)
    if name is not None and name.strip():
        i = stop_index(bus_id, name)
        if i is None:
            raise HTTPException(status_code=422, detail=f"Unknown {label} stop '{name}' for {bus_id}. "
                                                        f"Stops in travel order: {', '.join(stops)}")
        if index is not None and index != i:
            raise HTTPException(status_code=422, detail=f"{label}_index {index} does not match {label} '{name}' "
                                                        f"(index {i} in {bus_id}'s direction)")
        return i
    if index is None:
        raise HTTPException(status_code=422, detail=f"{label} (name) or {label}_index is required")
    if not 0 <= index < len(stops):
        raise HTTPException(status_code=422, detail=f"{label}_index {index} out of range 0..{len(stops) - 1}")
    return index


@app.post("/api/issue_ticket")
def issue_ticket(event: TicketEvent):
    """
    Called by the ETM module when a ticket is printed.
    Saves ONE ticket row on the bus's current trip and returns the new onboard count.
    Normal path: 3 Supabase calls (state row, insert, trip tickets).
    """
    try:
        bus_id = (event.bus_id or "").strip()
        stops = stops_for(bus_id)
        oi = resolve_stop(bus_id, event.origin, event.origin_index, "origin")
        di = resolve_stop(bus_id, event.destination, event.destination_index, "destination")
        if di <= oi:
            raise HTTPException(status_code=422, detail=f"Destination '{stops[di]}' is not after origin "
                                                        f"'{stops[oi]}' for {bus_id}")
        if event.ticket_count < 1:
            raise HTTPException(status_code=422, detail="ticket_count must be >= 1")
        ticket_type = (event.ticket_type or "full").strip().lower()
        if ticket_type not in FARE_PER_PASSENGER:
            raise HTTPException(status_code=422, detail=f"Invalid ticket_type '{event.ticket_type}'. "
                                                        f"Use one of: {', '.join(FARE_PER_PASSENGER)}")
        client_supplied_id = bool(event.client_event_id)
        if client_supplied_id:
            try:
                cid = str(uuid.UUID(event.client_event_id))
            except ValueError:
                raise HTTPException(status_code=422, detail="client_event_id must be a UUID")
        else:
            # Server-side id makes our own connection retries idempotent too.
            cid = str(uuid.uuid4())
        fare = FARE_PER_PASSENGER[ticket_type] * event.ticket_count

        row = ensure_trip(bus_id, fetch_state_row(bus_id))
        trip_id = row["current_trip_id"]

        duplicate = False
        try:
            db(lambda c: c.table("ticket_events").insert({
                "bus_id": bus_id,
                "trip_id": trip_id,
                "origin": stops[oi],
                "destination": stops[di],
                "origin_index": oi,
                "destination_index": di,
                "ticket_count": event.ticket_count,
                "ticket_type": ticket_type,
                "fare": fare,
                "client_event_id": cid,
                "timestamp": now_iso(),
            }))
        except APIError as e:
            if getattr(e, "code", None) != "23505":
                raise
            # Same client_event_id already stored. If WE generated the id, this was our own retry landing twice.
            duplicate = client_supplied_id

        idx = int(row.get("current_stop_index") or 0)
        state = compute_state(bus_id, row, fetch_trip_tickets(trip_id, idx))
        return {
            "status": "success",
            "duplicate": duplicate,
            "message": "duplicate ignored" if duplicate else f"{event.ticket_count} tickets issued",
            "client_event_id": cid,
            "ticket_type": ticket_type,
            "fare": fare,
            **state,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise server_error("issue_ticket", e)


@app.get("/api/bus_state/{bus_id}")
def get_bus_state(bus_id: str):
    """
    Called by the Passenger PWA / ETM to get the current live occupancy.
    Computed from the current trip's tickets only. 2 Supabase calls (1 if the bus has no trip).
    """
    try:
        stops_for(bus_id)  # 422 for unknown bus
        row = fetch_state_row(bus_id)
        if not row or not row.get("current_trip_id"):
            return compute_state(bus_id, row, [])
        idx = int(row.get("current_stop_index") or 0)
        return compute_state(bus_id, row, fetch_trip_tickets(row["current_trip_id"], idx))
    except HTTPException:
        raise
    except Exception as e:
        raise server_error("bus_state", e)


@app.get("/api/bus_states")
def get_bus_states(ids: Optional[str] = None):
    """
    Batch version of /api/bus_state: ?ids=AP-16-1234,AP-16-4023 (all buses if omitted).
    Always 2 Supabase calls regardless of how many buses.
    """
    try:
        requested = [i.strip() for i in (ids or "").split(",") if i.strip()] or list(BUS_DIRECTION)
        requested = list(dict.fromkeys(requested))
        known = [b for b in requested if b in BUS_DIRECTION]
        unknown = [b for b in requested if b not in BUS_DIRECTION]
        if not known:
            raise HTTPException(status_code=422, detail=f"No known bus ids in '{ids}'")

        rows_res = db(lambda c: c.table("live_bus_state").select(STATE_COLS).in_("bus_id", known))
        rows = {r["bus_id"]: r for r in (rows_res.data or [])}
        trip_ids = [r["current_trip_id"] for r in rows.values() if r.get("current_trip_id")]

        tickets_by_trip: dict = {}
        if trip_ids:
            min_idx = min(int(rows[b].get("current_stop_index") or 0) for b in rows if rows[b].get("current_trip_id"))
            t_res = db(lambda c: c.table("ticket_events")
                       .select("trip_id,destination_index,ticket_count")
                       .in_("trip_id", trip_ids)
                       .gt("destination_index", min_idx))
            data = t_res.data or []
            if len(data) >= 1000:
                log.error("bus_states: %d ticket rows returned, may be truncated by the API row limit", len(data))
            for t in data:
                tickets_by_trip.setdefault(t["trip_id"], []).append(t)

        buses = {}
        for b in known:
            row = rows.get(b)
            trip = (row or {}).get("current_trip_id")
            buses[b] = compute_state(b, row, tickets_by_trip.get(trip, []) if trip else [])
        return {"buses": buses, "unknown": unknown, "server_time": now_iso()}
    except HTTPException:
        raise
    except Exception as e:
        raise server_error("bus_states", e)


@app.post("/api/advance_stop/{bus_id}")
def advance_stop(bus_id: str):
    """
    Demo GPS stand-in: snapshot onboard at the current stop, then move one stop forward.
    Never moves backward or past the last stop. Normal path: 4 Supabase calls.
    """
    try:
        stops = stops_for(bus_id)
        last = len(stops) - 1
        row = ensure_trip(bus_id, fetch_state_row(bus_id))
        trip_id = row["current_trip_id"]
        idx = min(max(int(row.get("current_stop_index") or 0), 0), last)
        tickets = fetch_trip_tickets(trip_id, idx)
        departing = compute_state(bus_id, row, tickets)["onboard"]

        if idx >= last:
            state = compute_state(bus_id, row, tickets)
            return {"moved": False, "message": "Already at the last stop", "onboard_departing": departing, **state}

        ts = now_iso()
        db(lambda c: c.table("trip_snapshots").upsert({
            "trip_id": trip_id, "stop_index": idx, "onboard_count": departing, "timestamp": ts,
        }, on_conflict="trip_id,stop_index"))
        new_fields = {"current_stop_index": idx + 1, "last_stop_name": stops[idx + 1], "last_updated": ts}
        upd = db(lambda c: c.table("live_bus_state").update(new_fields)
                 .eq("bus_id", bus_id).eq("current_trip_id", trip_id).eq("current_stop_index", idx))
        if not upd.data:
            raise HTTPException(status_code=409, detail="Bus position changed concurrently; please retry")

        state = compute_state(bus_id, {**row, **new_fields}, tickets)
        return {"moved": True, "onboard_departing": departing, **state}
    except HTTPException:
        raise
    except Exception as e:
        raise server_error("advance_stop", e)


class ResetTrip(BaseModel):
    seat_capacity: Optional[int] = None


@app.post("/api/reset_trip/{bus_id}")
def reset_trip(bus_id: str, seat_capacity: Optional[int] = None, body: Optional[ResetTrip] = Body(None)):
    """
    Start a new trip for the bus (capacity from body or ?seat_capacity=, default 50) at stop index 0.
    Old tickets are never deleted; they simply belong to the previous trip. 2 Supabase calls.
    """
    try:
        stops = stops_for(bus_id)
        cap = (body.seat_capacity if body and body.seat_capacity is not None else seat_capacity) or DEFAULT_CAPACITY
        if not 1 <= cap <= 500:
            raise HTTPException(status_code=422, detail="seat_capacity must be between 1 and 500")
        ts = now_iso()
        trip = db(lambda c: c.table("trips").insert({
            "bus_id": bus_id, "seat_capacity": cap, "is_legacy": False, "start_time": ts}))
        trip_id = trip.data[0]["id"]
        res = db(lambda c: c.table("live_bus_state").upsert({
            "bus_id": bus_id,
            "current_trip_id": trip_id,
            "current_stop_index": 0,
            "seat_capacity": cap,
            "last_stop_name": stops[0],
            "last_updated": ts,
        }, on_conflict="bus_id"))
        row = res.data[0] if res.data else {"current_trip_id": trip_id, "current_stop_index": 0,
                                            "seat_capacity": cap, "last_stop_name": stops[0], "last_updated": ts}
        return {"reset": True, **compute_state(bus_id, row, [])}
    except HTTPException:
        raise
    except Exception as e:
        raise server_error("reset_trip", e)


@app.get("/api/dropoffs/{bus_id}")
def get_dropoffs(bus_id: str):
    """
    Legacy endpoint: per-stop drop-off counts for the current trip (ahead of the bus only).
    """
    state = get_bus_state(bus_id)
    return {"dropoffs": [{"stop": f["stop"], "count": f["count"]} for f in state["drop_off_forecast"]]}

# Run via: uvicorn main:app --reload
