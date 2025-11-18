import sqlite3
conn = sqlite3.connect("D:/CARBONTALLY/carbontallyfinalized/CarbonTally-main/Carbontally App/data/field_agent_passwords.db")
cursor = conn.execute("PRAGMA table_info(field_agent_access)")
for row in cursor:
    print(row)
conn.close()
