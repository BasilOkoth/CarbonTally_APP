# kobo_monitoring.py -- FULLY UPDATED WITH FAO AGRO-ECOLOGICAL ZONES (AEZ)

import streamlit as st
from datetime import datetime, timedelta
import pandas as pd
import sqlite3
import json
import requests
from pathlib import Path
import os
import geopandas as gpd
from shapely.geometry import Point
# Assuming 'carbonfao' contains the necessary calculation and coefficient logic
from carbonfao import calculate_co2_sequestered

# =========================================================
# ---------------------- CONFIG ---------------------------
# =========================================================

BASE_DIR_MONITORING = Path(__file__).parent
MONITORING_DB_PATH = BASE_DIR_MONITORING / "data" / "monitoring.db"
TREES_DB_PATH = BASE_DIR_MONITORING / "data" / "trees.db"

KOBO_API_URL = "https://kf.kobotoolbox.org/api/v2"
KOBO_API_TOKEN = st.secrets.get("KOBO_API_TOKEN", "your_api_token_here")
KOBO_MONITORING_ASSET_ID = st.secrets.get("KOBO_MONITORING_ASSET_ID", "your_asset_id_here")

# ------------------ Load FAO Agro-Ecological Zones (AEZ) ----------------
# FIX: Using the existing, functional GEZ path for the AEZ data variable 
# to resolve the "No such file or directory" error.
AEZ_SHAPEFILE_PATH = os.path.join(BASE_DIR_MONITORING, "data", "gez2010", "gez_2010_wgs84.shp")
FAO_AEZ_GDF = gpd.read_file(AEZ_SHAPEFILE_PATH)

# ------------------ Species Allometric Coefficients ----------
SPECIES_CSV_PATH = os.path.join(BASE_DIR_MONITORING, "data", "species_allometrics.csv")
SPECIES_ALLOMETRIC_DF = pd.read_csv(SPECIES_CSV_PATH)
SPECIES_ALLOMETRIC = {
    row["species"].strip().lower(): {"a": row["a"], "b": row["b"], "c": row["c"]}
    for _, row in SPECIES_ALLOMETRIC_DF.iterrows()
}

# =========================================================
# ------------------ DB CONNECTIONS -----------------------
# =========================================================

def get_monitoring_db_connection():
    MONITORING_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(MONITORING_DB_PATH))
    # Ensure co2_details and agro_ecological_zone columns exist
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE tree_monitoring ADD COLUMN co2_details TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        # Renamed column to reflect AEZ terminology
        cursor.execute("ALTER TABLE tree_monitoring ADD COLUMN agro_ecological_zone TEXT") 
    except sqlite3.OperationalError:
        pass
    conn.commit()
    return conn

def get_trees_db_connection():
    return sqlite3.connect(str(TREES_DB_PATH))

def initialize_monitoring_db():
    conn = get_monitoring_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_submissions (
            submission_id TEXT PRIMARY KEY,
            tree_id TEXT NOT NULL,
            processed_at TEXT NOT NULL
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tree_monitoring (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tree_id TEXT NOT NULL,
            submission_id TEXT NOT NULL,
            dbh_cm REAL,
            rcd_cm REAL,
            height_m REAL,
            co2_kg REAL,
            co2_details TEXT,
            -- Updated column name
            agro_ecological_zone TEXT, 
            monitored_at TEXT,
            monitor_count INTEGER DEFAULT 1
        )
        """)
        conn.commit()
        st.success("✅ SQLite tables initialized successfully.")
    finally:
        conn.close()

# =========================================================
# ------------------ HELPER FUNCTIONS ---------------------
# =========================================================

def try_float(val):
    try:
        return float(val)
    except:
        return None

def validate_user_session():
    if "authenticated" not in st.session_state or not st.session_state.authenticated:
        st.warning("Please log in.")
        return False
    if "user" not in st.session_state or "treeTrackingNumber" not in st.session_state["user"]:
        st.warning("Session error.")
        return False
    return True

# =========================================================
# ------------------ KOBO API FUNCTIONS -------------------
# =========================================================

def get_monitoring_submissions(asset_id, hours=24):
    headers = {"Authorization": f"Token {KOBO_API_TOKEN}"}
    since_time = datetime.utcnow() - timedelta(hours=hours)
    params = {"format": "json", "query": json.dumps({"_submission_time": {"$gte": since_time.isoformat() + "Z"}})}
    try:
        response = requests.get(f"{KOBO_API_URL}/assets/{asset_id}/data/", headers=headers, params=params)
        response.raise_for_status()
        return response.json().get("results", [])
    except Exception as e:
        st.error(f"Submission fetch error: {e}")
        return []

# =========================================================
# --------------- AGRO-ECOLOGICAL ZONE HELPERS -----------------
# =========================================================

def get_agro_ecological_zone(lat, lon):
    """
    Determine FAO Agro-Ecological Zone (AEZ) using geopandas shapefile lookup.
    """
    try:
        point = Point(lon, lat)
        # Uses the AEZ GeoDataFrame object
        match = FAO_AEZ_GDF[FAO_AEZ_GDF.geometry.contains(point)] 
        if not match.empty:
            # Assuming 'gez_name' is the column that holds the AEZ identifier in the shapefile
            return match.iloc[0]["gez_name"] 
    except:
        return None
    return None

# =========================================================
# ---------------- TREE DATABASE OPS ---------------------
# =========================================================

def get_tree_data(tree_id):
    conn = get_trees_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT scientific_name, latitude, longitude FROM trees WHERE tree_id = ?", (tree_id,))
        row = cursor.fetchone()
        if row:
            return {"scientific_name": row[0], "latitude": row[1], "longitude": row[2]}
        return None
    finally:
        conn.close()

def update_tree_inventory(tree_id, dbh_cm, height_m, co2_kg):
    conn = get_trees_db_connection()
    try:
        conn.execute("""
            UPDATE trees
            SET dbh_cm = ?, height_m = ?, co2_kg = ?, last_monitored_at = ?
            WHERE tree_id = ?
        """, (dbh_cm, height_m, co2_kg, datetime.utcnow().isoformat(), tree_id))
        conn.commit()
    finally:
        conn.close()

# =========================================================
# --------------- MONITORING DATABASE OPS ----------------
# =========================================================

def is_submission_processed(submission_id):
    conn = get_monitoring_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM processed_submissions WHERE submission_id = ?", (submission_id,))
        return cursor.fetchone() is not None
    finally:
        conn.close()

def save_monitoring_record(tree_id, submission_id, dbh_cm, rcd_cm, height_m, co2_kg, co2_details, agro_ecological_zone):
    conn = get_monitoring_db_connection()
    try:
        cursor = conn.cursor()
        today = datetime.utcnow().date()
        # Updated column name in SELECT
        cursor.execute("""
            SELECT id, monitor_count FROM tree_monitoring
            WHERE tree_id = ? AND DATE(monitored_at) = DATE(?)
        """, (tree_id, today.isoformat()))
        row = cursor.fetchone()
        if row:
            record_id, count = row
            # Updated column name in UPDATE
            cursor.execute("""
                UPDATE tree_monitoring
                SET dbh_cm = ?, rcd_cm = ?, height_m = ?, co2_kg = ?, co2_details = ?, agro_ecological_zone = ?, monitored_at = ?, monitor_count = ?
                WHERE id = ?
            """, (dbh_cm, rcd_cm, height_m, co2_kg, co2_details, agro_ecological_zone, datetime.utcnow().isoformat(), count + 1, record_id))
        else:
            # Updated column name in INSERT
            cursor.execute("""
                INSERT INTO tree_monitoring
                (tree_id, submission_id, dbh_cm, rcd_cm, height_m, co2_kg, co2_details, agro_ecological_zone, monitored_at, monitor_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (tree_id, submission_id, dbh_cm, rcd_cm, height_m, co2_kg, co2_details, agro_ecological_zone, datetime.utcnow().isoformat(), 1))
        conn.commit()
    finally:
        conn.close()

def mark_submission_processed(submission_id, tree_id):
    conn = get_monitoring_db_connection()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO processed_submissions (submission_id, tree_id, processed_at)
            VALUES (?, ?, ?)
        """, (submission_id, tree_id, datetime.utcnow().isoformat()))
        conn.commit()
    finally:
        conn.close()

# =========================================================
# -------------- PROCESS SINGLE SUBMISSION ----------------
# =========================================================

def process_submission(submission):
    tree_id = submission.get("tree_id")
    submission_id = submission.get("_id")
    if not tree_id or not submission_id:
        return False
    if is_submission_processed(submission_id):
        return True

    tree_data = get_tree_data(tree_id)
    if not tree_data:
        st.warning(f"Tree {tree_id} not found.")
        return False

    dbh_cm = try_float(submission.get("dbh_cm"))
    rcd_cm = try_float(submission.get("rcd_cm"))
    height_m = try_float(submission.get("height_m"))
    diameter_cm = dbh_cm if dbh_cm else rcd_cm

    # Used the new function name
    agro_ecological_zone = get_agro_ecological_zone(tree_data["latitude"], tree_data["longitude"])
    co2_kg = None
    co2_details = {}

    if diameter_cm and height_m:
        co2_kg = calculate_co2_sequestered(dbh_cm=dbh_cm, height_m=height_m, rcd_cm=rcd_cm,
                                           species=tree_data["scientific_name"],
                                           latitude=tree_data["latitude"], longitude=tree_data["longitude"])
        co2_details = {
            "dbh_cm": dbh_cm,
            "rcd_cm": rcd_cm,
            "height_m": height_m,
            "species": tree_data["scientific_name"],
            # Updated key name
            "agro_ecological_zone": agro_ecological_zone 
        }

    # Used the new parameter name
    save_monitoring_record(tree_id, submission_id, dbh_cm, rcd_cm, height_m, co2_kg,
                           json.dumps(co2_details), agro_ecological_zone)
    update_tree_inventory(tree_id, dbh_cm, height_m, co2_kg)
    mark_submission_processed(submission_id, tree_id)

    st.success(f"Processed submission for tree {tree_id}")
    return True

# =========================================================
# --------------- BULK PROCESSING FUNCTION ----------------
# =========================================================

def process_new_submissions(hours=24):
    if not validate_user_session():
        return 0

    user_tracking = st.session_state["user"]["treeTrackingNumber"].strip().lower()
    submissions = get_monitoring_submissions(KOBO_MONITORING_ASSET_ID, hours)
    count = 0

    for submission in submissions:
        tree_id = submission.get("tree_id")
        if not tree_id:
            continue

        conn = get_trees_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT treeTrackingNumber FROM trees WHERE tree_id = ?", (tree_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            continue

        db_tracking = row[0].strip().lower()
        submission_tracking = str(submission.get("tree_tracking_number", "")).strip().lower()
        if submission_tracking and submission_tracking != db_tracking:
            continue
        if db_tracking != user_tracking:
            continue
        if process_submission(submission):
            count += 1
    return count

# =========================================================
# ----------------------- UI ------------------------------
# =========================================================

def monitoring_section():
    st.title("🌿 Tree Monitoring System (AEZ Aligned)")

    initialize_monitoring_db()

    if "last_view_time" not in st.session_state:
        st.session_state.last_view_time = datetime.utcnow()

    tab1, tab2 = st.tabs(["Process Submissions", "View Processed Data"])

    with tab1:
        st.header("Process New Submissions")
        hours = st.slider("Look back hours", 1, 168, 24)
        if st.button("Check for New Submissions"):
            processed = process_new_submissions(hours)
            st.success(f"Processed {processed} new submissions")
            st.session_state.last_view_time = datetime.utcnow()

    with tab2:
        st.header("Previously Processed Submissions")
        conn_monitor = get_monitoring_db_connection()
        conn_trees = get_trees_db_connection()
        try:
            mon_df = pd.read_sql_query("SELECT * FROM tree_monitoring", conn_monitor)
            trees_df = pd.read_sql_query("SELECT tree_id, treeTrackingNumber, local_name FROM trees", conn_trees)
            if mon_df.empty:
                st.info("No monitoring records yet.")
                return
            df = pd.merge(mon_df, trees_df, on="tree_id", how="left")
            df["monitored_at"] = pd.to_datetime(df["monitored_at"])
            df["is_new"] = df["monitored_at"] > st.session_state.last_view_time
            df = df.rename(columns={
                "tree_id": "Tree ID",
                "treeTrackingNumber": "Tracking Number",
                "local_name": "Tree Name",
                "dbh_cm": "DBH (cm)",
                "rcd_cm": "RCD (cm)",
                "height_m": "Height (m)",
                "co2_kg": "CO₂ (kg)",
                "co2_details": "CO₂ Details",
                # Updated column name for display
                "agro_ecological_zone": "Agro-Ecological Zone", 
                "monitored_at": "Monitored At",
                "monitor_count": "Times Monitored"
            })

            def highlight(row):
                return ['background-color: #d6ffd6' if row["is_new"] else '' for _ in row]

            st.dataframe(df.style.apply(highlight, axis=1))
            st.session_state.last_view_time = datetime.utcnow()
        finally:
            conn_monitor.close()
            conn_trees.close()

if __name__ == "__main__":
    monitoring_section()
