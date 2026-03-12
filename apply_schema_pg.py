import psycopg2

def try_connect(pwd):
    print(f"Trying password: {pwd}")
    try:
        conn = psycopg2.connect(
            host="aws-1-ap-northeast-2.pooler.supabase.com",
            port=5432,
            user="postgres.aohtgcjyhocbzvxnmdwk",
            password=pwd,
            dbname="postgres"
        )
        print(f"Success with password: {pwd}")
        return conn
    except Exception as e:
        print(f"Failed with password {pwd}: {e}")
        return None

if __name__ == "__main__":
    conn = try_connect("Travellobus@0821")
    if not conn:
        conn = try_connect("[Travellobus@0821]")
        
    if conn:
        with open('backend/schema.sql', 'r') as f:
            sql = f.read()
        try:
            with conn.cursor() as cur:
                # We will directly run the create table command only.
                query = """
                CREATE TABLE IF NOT EXISTS bus_dropoffs (
                    bus_id TEXT NOT NULL,
                    stop_name TEXT NOT NULL,
                    dropoff_count INT NOT NULL DEFAULT 0,
                    last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (bus_id, stop_name)
                );
                """
                cur.execute(query)
                conn.commit()
                print("bus_dropoffs table created successfully!")
        except Exception as e:
            print("Failed to run query:", e)
        finally:
            conn.close()
    else:
        print("Could not connect with either password.")
