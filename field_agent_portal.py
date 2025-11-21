import streamlit as st
import pandas as pd
import sqlite3
from pathlib import Path
import geopy.distance
import math
from streamlit_js_eval import streamlit_js_eval

# ----------------- CONFIG -----------------
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
TREES_DB = DATA_DIR / "trees.db"

# ----------------- HELPERS -----------------
@st.cache_data
def get_trees_df():
    conn = sqlite3.connect(TREES_DB)
    df = pd.read_sql_query(
        "SELECT tree_id, local_name, scientific_name, latitude, longitude, treeTrackingNumber, planters_name FROM trees",
        conn
    )
    conn.close()
    return df

def generate_qr_code(data):
    """Placeholder for QR code generation."""
    return f"QR_CODE_FOR_{data}"

def get_kobo_secrets():
    """Fetch Kobo secrets from Streamlit's secrets.toml."""
    # Note: These keys MUST match the entries in your .streamlit/secrets.toml
    api_token = st.secrets["KOBO_API_TOKEN"]
    asset_id = st.secrets["KOBO_ASSET_ID"]
    form_code = st.secrets["KOBO_ASSET_FORM_CODE"]             # Planting Form Code
    monitoring_asset_id = st.secrets["KOBO_MONITORING_ASSET_ID"]
    monitoring_form_code = st.secrets["KOBO_MONITORING_ASSET"] # Monitoring Form Code
    return api_token, asset_id, form_code, monitoring_asset_id, monitoring_form_code

def get_bearing(lat1, lon1, lat2, lon2):
    """Calculates the bearing (initial direction) from point 1 to point 2."""
    dLon = math.radians(lon2 - lon1)
    y = math.sin(dLon) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dLon)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360) % 360

def bearing_to_compass(bearing):
    """Converts bearing degrees to a compass direction string."""
    directions = ["North", "North-East", "East", "South-East", "South", "South-West", "West", "North-West"]
    ix = round(bearing / 45) % 8
    return directions[ix]

def find_nearby_trees(lat, lon, trees_dataframe, tracking_number):
    nearby = []
    # Filter the DataFrame for the specific tracking number
    df_filtered = trees_dataframe[trees_dataframe["treeTrackingNumber"] == tracking_number]

    for _, row in df_filtered.iterrows():
        if pd.notna(row["latitude"]) and pd.notna(row["longitude"]):
            # Use distance function from geopy.distance
            dist = geopy.distance.distance((row["latitude"], row["longitude"]), (lat, lon)).m
            if 3 <= dist <= 5: # Range of 3 to 5 meters
                bearing = get_bearing(lat, lon, row["latitude"], row["longitude"])
                direction = bearing_to_compass(bearing)
                nearby.append({
                    "Tree ID": row["tree_id"],
                    "Species": row["local_name"],
                    "Distance (m)": round(dist, 2),
                    "Direction": direction,
                    "Planted By": row["planters_name"]
                })
    return pd.DataFrame(nearby)

# ----------------- PORTAL -----------------
def field_agent_portal_ui():
    st.markdown("""
        <style>
            .section-header {
                font-size: 1.5rem;
                font-weight: 600;
                margin-top: 2rem;
                color: #1D7749;
            }
            .custom-button,
            div.stButton > button#find-nearby-btn,
            div.stButton > button#logout-field-btn {
                background-color: #1D7749 !important;
                color: white !important;
                padding: 0.6em 1.2em;
                font-size: 1rem;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                text-decoration: none;
                display: inline-block;
                margin-top: 0.5rem;
            }
            .custom-button:hover,
            div.stButton > button#find-nearby-btn:hover,
            div.stButton > button#logout-field-btn:hover {
                background-color: #166534 !important;
            }
        </style>
    """, unsafe_allow_html=True)

    st.title("🌍 Field Agent Portal")

    # ====================================================================
    # 🎯 NEW: Call the helper function to fetch Kobo secrets from .toml
    # ====================================================================
    try:
        (
            KOBO_API_TOKEN,
            KOBO_ASSET_ID,
            KOBO_FORM_CODE,             # Planting Form Code
            KOBO_MONITORING_ASSET_ID,
            KOBO_MONITORING_FORM_CODE   # Monitoring Form Code
        ) = get_kobo_secrets()
    except KeyError as e:
        st.error(f"⚠️ Configuration Error: Could not find KoBo secret key {e} in your secrets.toml file.")
        st.warning("Please verify all five keys in your `secrets.toml` are correctly defined.")
        return
    # ====================================================================

    field_access_granted = st.session_state.get("field_agent_authenticated", False)
    entered_tracking_number = st.session_state.get("field_agent_tracking_number", None)
    field_agent_name = st.session_state.get("field_agent_name", "Field Agent")

    if not field_access_granted:
        st.warning("🚫 You must log in to access the Field Agent Portal.")
        if st.button("🔐 Go to Field Agent Login"):
            st.session_state.page = "FieldAgentLogin"
            st.rerun()
        return

    st.success(f"✅ Welcome, **{field_agent_name}** — Access granted for tracking number: `{entered_tracking_number}`")

    # Establish database connection and load data
    try:
        conn = sqlite3.connect(str(TREES_DB))
        trees_df = pd.read_sql_query("""
            SELECT tree_id, local_name, scientific_name, latitude, longitude, treeTrackingNumber, planters_name
            FROM trees
        """, conn)
        conn.close()
    except Exception as e:
        st.error(f"Failed to load tree database: {e}")
        return


    st.markdown('<div class="section-header">🌐 How to Monitor Trees</div>', unsafe_allow_html=True)
    st.markdown("""
You can monitor a tree in two ways:

- 📷 **Scan a QR Code** attached to the tree (using your camera or scanner)
- 📍 **Find a Nearby Tree** using your GPS location (**3–5 meters range**)
""")

    st.markdown('<div class="section-header">📍 Your GPS Location</div>', unsafe_allow_html=True)

    # Initialize session state for user location if not present
    if "user_lat" not in st.session_state:
        st.session_state["user_lat"] = None
    if "user_lon" not in st.session_state:
        st.session_state["user_lon"] = None

    user_lat = st.session_state["user_lat"]
    user_lon = st.session_state["user_lon"]

    # --- Location Acquisition Logic (Unchanged) ---
    if user_lat is None or user_lon is None:
        st.info("⏳ Fetching your current GPS location...")
        loc = streamlit_js_eval(
            js_expressions="""
            new Promise((resolve, reject) => {
                navigator.geolocation.getCurrentPosition(
                    (position) => resolve({coords: {latitude: position.coords.latitude, longitude: position.coords.longitude}}),
                    (error) => {
                        console.error("Geolocation error:", error);
                        resolve({error: error.message}); // Resolve with error info
                    },
                    { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 } // Options for better accuracy
                );
            })
            """,
            key="getGeo"
        )

        if loc:
            if "coords" in loc:
                st.session_state["user_lat"] = loc["coords"]["latitude"]
                st.session_state["user_lon"] = loc["coords"]["longitude"]
                user_lat = st.session_state["user_lat"]
                user_lon = st.session_state["user_lon"]
                st.success(f"📍 Location found: **Latitude {user_lat:.5f}, Longitude {user_lon:.5f}**")
                st.rerun()
            elif "error" in loc:
                st.error(f"⚠️ Geolocation error: {loc['error']}. Please ensure location access is granted.")
                st.info("If it doesn’t prompt you, reset your location permission in the browser settings.")
            else:
                st.warning("⚠️ Please allow GPS location in your browser to find nearby trees.")
                st.info("If it doesn’t prompt you, reset your location permission in the browser settings.")
    else:
        st.success(f"📍 Location found: **Latitude {user_lat:.5f}, Longitude {user_lon:.5f}**")
    # -----------------------------------------------

    st.markdown('<div class="section-header">🌲 Find Nearby Trees</div>', unsafe_allow_html=True)

    if "find_nearby" not in st.session_state:
        st.session_state["find_nearby"] = False

    if st.button("🔍 Find Trees Nearby", key="find-nearby-btn", disabled=(user_lat is None or user_lon is None)):
        st.session_state["find_nearby"] = True

    if st.session_state.get("find_nearby"):
        if user_lat and user_lon:
            nearby = find_nearby_trees(user_lat, user_lon, trees_df, entered_tracking_number)
            if not nearby.empty:
                st.success(f"🎉 Found {len(nearby)} tree(s) within 3–5 meters.")
                st.dataframe(nearby)

                if "Tree ID" in nearby.columns and not nearby["Tree ID"].empty:
                    selected_tree_id = st.selectbox("Select a tree to monitor", nearby["Tree ID"])
                    if st.button("📋 Monitor This Tree"):
                        # Use the form code retrieved from the secrets.toml via get_kobo_secrets()
                        form_url = f"https://ee.kobotoolbox.org/x/{KOBO_MONITORING_FORM_CODE}?tree_id={selected_tree_id}&treeTrackingNumber={entered_tracking_number}&latitude={user_lat:.5f}&longitude={user_lon:.5f}"

                        st.markdown(f'<a href="{form_url}" target="_blank" class="custom-button">📝 Open Monitoring Form for Tree {selected_tree_id}</a>', unsafe_allow_html=True)
                        st.info("The monitoring form has been opened in a new tab.")
                else:
                    st.info("No Tree IDs available to select.")
            else:
                st.info("No trees found within 3–5 meters.")
        else:
            st.error("🌐 Location not available. Please ensure location access is granted and try again.")


    st.markdown('<div class="section-header">🌱 Plant a New Tree</div>', unsafe_allow_html=True)

    # Pre-fill location data into the planting URL if available
    planting_coords = ""
    if user_lat and user_lon:
        planting_coords = f"&latitude={user_lat:.5f}&longitude={user_lon:.5f}"

    # Use the form code retrieved from the secrets.toml via get_kobo_secrets()
    planting_url = f"https://ee.kobotoolbox.org/x/{KOBO_FORM_CODE}?treeTrackingNumber={entered_tracking_number}{planting_coords}"
    st.markdown("Click the button below to record a newly planted tree using the official form:")

    st.markdown(f"""
    <a href="{planting_url}" target="_blank">
        <button class="custom-button" style="margin-top: 10px;">
            ➕ Fill Planting Form
        </button>
    </a>
    """, unsafe_allow_html=True)

    st.markdown('<div class="section-header">📋 All Submitted Trees</div>', unsafe_allow_html=True)
    submitted = trees_df[trees_df["treeTrackingNumber"] == entered_tracking_number]
    if submitted.empty:
        st.info("You have not submitted any trees yet.")
    else:
        st.markdown(f"**Total trees recorded:** {len(submitted)}")
        st.dataframe(submitted.sort_values(by="tree_id", ascending=False))

    st.markdown("---")
    if st.button("🚪 Logout from Field Portal", key="logout-field-btn"):
        st.session_state.field_agent_authenticated = False
        st.session_state.field_agent_tracking_number = None
        st.session_state.field_agent_name = None
        st.session_state["user_lat"] = None
        st.session_state["user_lon"] = None
        st.session_state.page = "Landing"
        st.rerun()
