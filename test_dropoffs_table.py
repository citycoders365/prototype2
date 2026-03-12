from supabase import create_client, Client
import os

SUPABASE_URL = "https://aohtgcjyhocbzvxnmdwk.supabase.co"
SUPABASE_KEY = "sb_publishable_vBoZvNOIgcSfeYcp4PjnHQ_2pcnqNVG"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

try:
    print("Testing GET on bus_dropoffs...")
    res = supabase.table("bus_dropoffs").select("*").execute()
    print("GET Response:", res.data)
    print("Table bus_dropoffs exists and is accessible!")
except Exception as e:
    print("Error accessing bus_dropoffs:", e)
