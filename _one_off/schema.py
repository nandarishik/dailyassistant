import sqlite3
import pprint

db_path = r'c:\Users\Admin\Desktop\BrainPowerInternship\QAFFEINE_Prototype\database\AI_DATABASE.DB'
try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print("Tables in AI_DATABASE.DB:")
    for table_name in tables:
        table_name = table_name[0]
        print(f"\n--- Table: {table_name} ---")
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = cursor.fetchall()
        for col in columns:
            print(f"  {col[1]} ({col[2]})")
        
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        print(f"  Total row count: {count}")
        
        print(f"  Sample 3 rows:")
        cursor.execute(f"SELECT * FROM {table_name} LIMIT 3;")
        sample = cursor.fetchall()
        for row in sample:
            print(f"  {row}")

    conn.close()
except Exception as e:
    print("Error:", e)
