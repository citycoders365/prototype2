import os
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://aohtgcjyhocbzvxnmdwk.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_vBoZvNOIgcSfeYcp4PjnHQ_2pcnqNVG")

# Need service role key for table creation, but the publishable key might not suffice for DDL
print("Attempting to connect to Supabase to verify we can run raw SQL...")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
query = """
CREATE TABLE IF NOT EXISTS bus_dropoffs (
    bus_id TEXT NOT NULL,
    stop_name TEXT NOT NULL,
    dropoff_count INT NOT NULL DEFAULT 0,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (bus_id, stop_name)
);
"""

try:
    # the client api usually doesn't permit raw SQL execution for DDL without the postgrest 'rpc' or direct postgres connection.
    res = supabase.rpc("exec_sql", {"query": query}).execute()
    print("Success:", res)
except Exception as e:
    print("Failed to run DDL via REST client. You may need to run the SQL directly in the Supabase Dashboard.")
    print("Error:", e)
    
