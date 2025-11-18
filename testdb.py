import sqlite3

conn = sqlite3.connect("data/monitoring.db")
cursor = conn.cursor()
cursor.execute("PRAGMA table_info(tree_monitoring);")
print(cursor.fetchall())
conn.close()
