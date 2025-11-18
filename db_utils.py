from pathlib import Path
import sqlite3
import pandas as pd

BASE_DIR  = Path(__file__).parent
DATA_DIR  = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True, parents=True)
SQLITE_DB = DATA_DIR / "trees.db"

def get_db_connection():
    return sqlite3.connect(SQLITE_DB)

def load_tree_data():
    """Load all tree data from database."""
    conn = get_db_connection()
    try:
        return pd.read_sql_query("SELECT * FROM trees", conn)
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()

def load_tree_data_by_tracking_number(tracking_number):
    """Load a single tree's data from the database by tracking number."""
    conn = get_db_connection()
    try:
        df = pd.read_sql_query(
            "SELECT * FROM trees WHERE tree_tracking_number = ?",
            conn,
            params=(tracking_number,),
        )
    except Exception:
        df = pd.DataFrame()
    finally:
        conn.close()

    if df.empty:
        return None
    return df.iloc[0].to_dict()
