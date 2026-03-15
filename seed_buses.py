import os
from supabase import create_client, Client

SUPABASE_URL = "https://aohtgcjyhocbzvxnmdwk.supabase.co"
SUPABASE_KEY = "sb_publishable_vBoZvNOIgcSfeYcp4PjnHQ_2pcnqNVG"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

buses_to_seed = [
    {"bus_id": "AP-16-4023", "total_capacity": 50, "occupied_seats": 0},
    {"bus_id": "AP-16-4024", "total_capacity": 50, "occupied_seats": 0},
    {"bus_id": "AP-16-4025", "total_capacity": 50, "occupied_seats": 0},
    {"bus_id": "AP-16-4026", "total_capacity": 50, "occupied_seats": 0}
]

print("Starting to seed database...")
try:
    # Use insert with upsert=True equivalent in supabase python (which is upsert method)
    response = supabase.table("live_bus_state").upsert(buses_to_seed).execute()
    print("Successfully seeded buses:")
    for bus in response.data:
        print(f" - {bus['bus_id']}")
except Exception as e:
    print("Error seeding database:", e)
