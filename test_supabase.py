from supabase import create_client, Client
import asyncio
import os

SUPABASE_URL = "https://aohtgcjyhocbzvxnmdwk.supabase.co"
SUPABASE_KEY = "sb_publishable_vBoZvNOIgcSfeYcp4PjnHQ_2pcnqNVG"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

try:
    print("Testing GET...")
    res = supabase.table("live_bus_state").select("total_capacity, occupied_seats").eq("bus_id", "AP-16-1234").execute()
    print("GET Response:", res.data)
except Exception as e:
    print("GET Error:", e)

try:
    print("Testing POST...")
    res = supabase.table("ticket_events").insert({
        "bus_id": "AP-16-1234",
        "origin": "Stop A",
        "destination": "Stop B",
        "ticket_count": 2
    }).execute()
    print("POST Response:", res.data)
except Exception as e:
    print("POST Error:", e)
