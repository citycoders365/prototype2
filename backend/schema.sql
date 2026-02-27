-- Run this in your Supabase SQL Editor

-- 1. Create the `ticket_events` table
CREATE TABLE ticket_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bus_id TEXT NOT NULL,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    ticket_count INT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Create the `live_bus_state` table
CREATE TABLE live_bus_state (
    bus_id TEXT PRIMARY KEY,
    total_capacity INT NOT NULL DEFAULT 60,
    occupied_seats INT NOT NULL DEFAULT 0,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Insert initial dummy data for the PoC bus
INSERT INTO live_bus_state (bus_id, total_capacity, occupied_seats)
VALUES ('AP-16-1234', 60, 0)
ON CONFLICT (bus_id) DO NOTHING;
