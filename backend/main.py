from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
import os

# Initialize FastAPI app
app = FastAPI(title="TravelloBus Backend PoC")

# Allow CORS for local HTML file testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Supabase client
# Ensure SUPABASE_URL and SUPABASE_KEY are set in your environment
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://aohtgcjyhocbzvxnmdwk.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_vBoZvNOIgcSfeYcp4PjnHQ_2pcnqNVG")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Define request schemas
class TicketEvent(BaseModel):
    bus_id: str
    origin: str
    destination: str
    ticket_count: int

@app.post("/api/issue_ticket")
async def issue_ticket(event: TicketEvent):
    """
    Called by the ETM module when a ticket is printed.
    Records the event and updates the live bus state.
    """
    try:
        # 1. Insert into ticket_events
        supabase.table("ticket_events").insert({
            "bus_id": event.bus_id,
            "origin": event.origin,
            "destination": event.destination,
            "ticket_count": event.ticket_count
        }).execute()

        return {"status": "success", "message": f"{event.ticket_count} tickets issued"}

    except Exception as e:
        print(f"Error processing ticket event: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/bus_state/{bus_id}")
async def get_bus_state(bus_id: str):
    """
    Called by the Passenger PWA to get the current live occupancy.
    """
    try:
        # Fetch static info (e.g. total_capacity) from live_bus_state
        res = supabase.table("live_bus_state").select("total_capacity").eq("bus_id", bus_id).execute()
        
        if not res.data:
            raise HTTPException(status_code=404, detail="Bus not found")
            
        state = res.data[0]
        
        # Calculate dynamic occupancy and dropoffs from ticket_events
        tickets_res = supabase.table("ticket_events").select("destination, ticket_count").eq("bus_id", bus_id).execute()
        
        total_occupied = 0
        dropoffs_map = {}
        for row in tickets_res.data:
            count = row["ticket_count"]
            dest = row["destination"]
            total_occupied += count
            dropoffs_map[dest] = dropoffs_map.get(dest, 0) + count
            
        state["occupied_seats"] = total_occupied
        
        # Format dropoffs for the frontend
        # The frontend expects objects like { stop: string, eta: string, count: int }
        dropoffs = [
            {"stop": dest, "count": count, "eta": "N/A"} 
            for dest, count in dropoffs_map.items()
        ]
        
        state["dropoffs"] = dropoffs
        
        return state
        
    except Exception as e:
        print(f"Error fetching bus state: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/dropoffs/{bus_id}")
async def get_dropoffs(bus_id: str):
    """
    Returns per-stop drop-off counts aggregated from all ticket_events for this bus.
    Used by the Passenger PWA to display the drop-off forecast panel.
    """
    try:
        res = supabase.table("ticket_events").select("destination, ticket_count").eq("bus_id", bus_id).execute()
        dropoffs: dict = {}
        for row in res.data:
            dest = row["destination"]
            dropoffs[dest] = dropoffs.get(dest, 0) + row["ticket_count"]
        return {"dropoffs": [{"stop": k, "count": v} for k, v in dropoffs.items()]}
    except Exception as e:
        print(f"Error fetching dropoffs: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# Run via: uvicorn main:app --reload
