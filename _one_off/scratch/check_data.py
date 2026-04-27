import sqlite3
import pandas as pd
from pathlib import Path

db_path = Path("database/AI_DATABASE.DB")
conn = sqlite3.connect(db_path)

print("--- Table: AI_TEST_INVOICEBILLREGISTER ---")
summary = pd.read_sql_query("""
    SELECT 
        SUBSTR(DT, 1, 7) as month, 
        COUNT(*) as row_count,
        ROUND(SUM(NETAMT), 2) as total_revenue
    FROM AI_TEST_INVOICEBILLREGISTER
    GROUP BY month
    ORDER BY month
""", conn)
print(summary)

conn.close()
