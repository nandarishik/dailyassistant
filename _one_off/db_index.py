import sqlite3
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB_PATH = BASE / "database" / "AI_DATABASE.DB"

def create_indexes():
    print(f"Connecting to {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_tax_loc ON AI_TEST_TAXCHARGED_REPORT(LOCATION_NAME);",
        "CREATE INDEX IF NOT EXISTS idx_tax_pname ON AI_TEST_TAXCHARGED_REPORT(PRODUCT_NAME);",
        "CREATE INDEX IF NOT EXISTS idx_tax_trnno ON AI_TEST_TAXCHARGED_REPORT(TRNNO);",
        "CREATE INDEX IF NOT EXISTS idx_inv_loc ON AI_TEST_INVOICEBILLREGISTER(LOCATION_NAME);",
        "CREATE INDEX IF NOT EXISTS idx_inv_trnno ON AI_TEST_INVOICEBILLREGISTER(TRNNO);",
    ]
    
    start_time = time.time()
    for idx_sql in indexes:
        print(f"Executing: {idx_sql}")
        cur.execute(idx_sql)
        
    conn.commit()
    conn.close()
    
    elapsed = time.time() - start_time
    print(f"Indexes created successfully in {elapsed:.2f} seconds.")

if __name__ == '__main__':
    create_indexes()
