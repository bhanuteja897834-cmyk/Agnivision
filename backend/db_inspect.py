import sqlite3

db_path = "/app/backend/data/agnivision.db"
print(f"DB path: {db_path}")

conn = sqlite3.connect(db_path)
c = conn.cursor()

# List all tables
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = c.fetchall()
print(f"\nTables: {[t[0] for t in tables]}")

for t in tables:
    tname = t[0]
    c.execute(f"SELECT COUNT(*) FROM [{tname}]")
    count = c.fetchone()[0]
    
    # Get columns
    c.execute(f"PRAGMA table_info([{tname}])")
    cols = c.fetchall()
    col_names = [col[1] for col in cols]
    print(f"\n--- {tname}: {count} rows ---")
    print(f"  Columns: {col_names}")
    
    # Show sample row
    if count > 0:
        c.execute(f"SELECT * FROM [{tname}] LIMIT 1")
        row = c.fetchone()
        for i, col in enumerate(col_names):
            val = row[i] if row[i] is not None else "NULL"
            if isinstance(val, str) and len(val) > 80:
                val = val[:80] + "..."
            print(f"    {col}: {val}")

# For FIRMS/hotspot tables, get date distribution
print("\n\n=== DATE DISTRIBUTION ===")
for t in tables:
    tname = t[0]
    c.execute(f"PRAGMA table_info([{tname}])")
    cols = c.fetchall()
    col_names = [col[1] for col in cols]
    
    date_cols = [cn for cn in col_names if any(k in cn.lower() for k in ['date','time','acq'])]
    if date_cols and tname != 'sqlite_sequence':
        for dc in date_cols:
            try:
                c.execute(f"SELECT MIN([{dc}]), MAX([{dc}]) FROM [{tname}] WHERE [{dc}] IS NOT NULL")
                r = c.fetchone()
                print(f"\n{tname}.{dc}: {r[0]} -> {r[1]}")
            except:
                pass
        
        # Group by date if there's a date column
        for dc in date_cols:
            if 'date' in dc.lower() and 'time' not in dc.lower():
                try:
                    c.execute(f"SELECT [{dc}], COUNT(*) FROM [{tname}] GROUP BY [{dc}] ORDER BY [{dc}]")
                    for r in c.fetchall():
                        print(f"  {r[0]}: {r[1]}")
                except:
                    pass
                break

conn.close()
