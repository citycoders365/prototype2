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

        # 2. Fetch the current bus state
        # In a real app we would use SQL functions or RPCs to prevent race conditions
        bus_state_res = supabase.table("live_bus_state").select("occupied_seats").eq("bus_id", event.bus_id).execute()
        
        if not bus_state_res.data:
            raise HTTPException(status_code=404, detail="Bus ID not found in live state table")
            
        current_occupied = bus_state_res.data[0]["occupied_seats"]
        new_occupied = current_occupied + event.ticket_count

        # 3. Update the bus state with new occupied seats
        supabase.table("live_bus_state").update({
            "occupied_seats": new_occupied,
            "last_updated": "now()"
        }).eq("bus_id", event.bus_id).execute()

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
        res = supabase.table("live_bus_state").select("total_capacity, occupied_seats").eq("bus_id", bus_id).execute()
        
        if not res.data:
            raise HTTPException(status_code=404, detail="Bus not found")
            
        return res.data[0]
        
    except Exception as e:
        print(f"Error fetching bus state: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# Run via: uvicorn main:app --reload
