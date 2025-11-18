# field_agent_portal.py
import streamlit as st
import sqlite3
import pandas as pd
from pathlib import Path
import geopy.distance
import math
from shared_agent_utils import TREES_DB
from streamlit_js_eval import streamlit_js_eval

# Simple QR placeholder (replace with your QR generator)
def generate_qr_placeholder(url):
    return f"QR({url})"

def get_trees_df():
    conn = sqlite3.connect(str(TREES_DB))
    df = pd.read_sql_query("SELECT tree_id, local_name, scientific_name, latitude, longitude, treeTrackingNumber, planters_name FROM trees", conn)
    conn.close()
    return df

def get_bearing(lat1, lon1, lat2, lon2):
    dLon = math.radians(lon2 - lon1)
    y = math.sin(dLon) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dLon)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360) % 360

def bearing_to_compass(bearing):
    directions = ["North","North-East","East","South-East","South","South-West","West","North-West"]
    ix = round(bearing / 45) % 8
    return directions[ix]

def find_nearby_trees(lat, lon, df, tracking_number, min_m=3, max_m=5):
    rows = []
    df_filtered = df[df["treeTrackingNumber"] == tracking_number]
    for _, r in df_filtered.iterrows():
        if pd.notna(r["latitude"]) and pd.notna(r["longitude"]):
            d = geopy.distance.distance((r["latitude"], r["longitude"]), (lat, lon)).m
            if min_m <= d <= max_m:
                bearing = get_bearing(lat, lon, r["latitude"], r["longitude"])
                rows.append({
                    "tree_id": r["tree_id"],
                    "local_name": r.get("local_name",""),
                    "distance_m": round(d,2),
                    "direction": bearing_to_compass(bearing),
                    "planters_name": r.get("planters_name","")
                })
    return pd.DataFrame(rows)

def field_agent_portal_ui():
    st.title("🌍 Field Agent Portal")
    if not st.session_state.get("field_agent_authenticated", False):
        st.warning("You must log in first.")
        if st.button("Go to Field Agent Login"):
            st.session_state.page = "FieldAgentLogin"
            st.experimental_rerun()
        return

    tracking = st.session_state.get("field_agent_tracking_number")
    name = st.session_state.get("field_agent_name", f"Field Agent {tracking}")
    st.success(f"Welcome, {name}. Tracking: `{tracking}`")

    # Load trees
    try:
        df = get_trees_df()
    except Exception as e:
        st.error(f"Could not load trees DB: {e}")
        return

    # Location / find nearby
    if "fa_lat" not in st.session_state:
        st.session_state["fa_lat"] = None
    if "fa_lon" not in st.session_state:
        st.session_state["fa_lon"] = None

    col1, col2 = st.columns([3,1])
    with col1:
        if st.session_state["fa_lat"] is None:
            st.info("Click 'Get Location' to fetch GPS coordinates.")
        else:
            st.success(f"Location: {st.session_state['fa_lat']:.5f}, {st.session_state['fa_lon']:.5f}")

    with col2:
        if st.button("📍 Get Location"):
            loc = streamlit_js_eval(
                js_expressions="""
                new Promise((resolve) => {
                    navigator.geolocation.getCurrentPosition(
                        (pos) => resolve({coords:{latitude:pos.coords.latitude, longitude:pos.coords.longitude}}),
                        (err) => resolve({error: err.message}),
                        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
                    );
                })
                """,
                key="fa_geo"
            )
            if loc and "coords" in loc:
                st.session_state["fa_lat"] = loc["coords"]["latitude"]
                st.session_state["fa_lon"] = loc["coords"]["longitude"]
                st.experimental_rerun()
            elif loc and "error" in loc:
                st.error(f"Geolocation error: {loc['error']}")

    st.markdown("### 🔎 Find Nearby Trees (3-5 m)")
    if st.button("Find Trees Nearby", disabled=(st.session_state["fa_lat"] is None or st.session_state["fa_lon"] is None)):
        st.session_state["fa_find"] = True
        st.experimental_rerun()

    if st.session_state.get("fa_find"):
        lat = st.session_state["fa_lat"]
        lon = st.session_state["fa_lon"]
        nearby = find_nearby_trees(lat, lon, df, tracking)
        if nearby.empty:
            st.info("No trees found within 3-5 meters.")
        else:
            st.success(f"Found {len(nearby)} tree(s)")
            st.dataframe(nearby)
            sel = st.selectbox("Select tree to monitor", nearby["tree_id"].tolist())
            if st.button("Open Monitoring Form"):
                monitor_form_code = st.secrets.get("KOBO_MONITORING_FORM_CODE", "")
                url = f"https://ee.kobotoolbox.org/x/{monitor_form_code}?tree_id={sel}&treeTrackingNumber={tracking}"
                st.markdown(f"[Open monitoring form for {sel}]({url})", unsafe_allow_html=True)
                st.write("QR (placeholder):", generate_qr_placeholder(url))

    st.markdown("### 🌱 Plant a New Tree")
    plant_form_code = st.secrets.get("KOBO_FORM_CODE", "")
    plant_url = f"https://ee.kobotoolbox.org/x/{plant_form_code}?treeTrackingNumber={tracking}"
    st.markdown(f"[Open planting form]({plant_url})", unsafe_allow_html=True)

    st.markdown("### 📋 All Submitted Trees (Your Tracking Number)")
    mytrees = df[df["treeTrackingNumber"] == tracking]
    if mytrees.empty:
        st.info("No trees submitted with this tracking number yet.")
    else:
        st.dataframe(mytrees.sort_values("tree_id", ascending=False))

    if st.button("Logout"):
        for k in ["field_agent_authenticated","field_agent_tracking_number","field_agent_name","fa_lat","fa_lon","fa_find"]:
            st.session_state.pop(k, None)
        st.experimental_rerun()
