# app.py - CarbonTally (Refactored & Fixed for Final Design)

import logging
from pathlib import Path
from datetime import datetime
import time
import sqlite3
import streamlit as st
from PIL import Image
import pandas as pd
import plotly.express as px

# ---------------------- CONFIG & PATHS ----------------------

# Define the logo path relative to the app structure for robustness
BASE_DIR = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "assets"
LOGO_FILE_NAME = "default_logo.png"
LOGO_PATH_RELATIVE = ASSETS_DIR / LOGO_FILE_NAME

# DB Paths
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SQLITE_DB = DATA_DIR / "trees.db"

# Page Icon Setup
icon_setting = "🌱" # Default icon fallback
if LOGO_PATH_RELATIVE.exists():
    try:
        page_logo = Image.open(str(LOGO_PATH_RELATIVE))
        icon_setting = page_logo
    except Exception:
        pass # Keep fallback if loading fails

st.set_page_config(page_title="CarbonTally", page_icon=icon_setting, layout="wide", initial_sidebar_state="expanded")

# ---------------------- LOGGER -----------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("carbontally")

# ---------------------- FIREBASE & MODULE FALLBACKS ----------------------
# (Retained your original structure for external module loading)

try:
    from firebase_auth_integration import (
        initialize_firebase, firebase_login_ui, firebase_signup_ui,
        firebase_password_recovery_ui, firebase_logout, get_current_firebase_user,
        check_firebase_user_role, init_sql_tables, sync_users_from_firestore,
        get_all_users
    )
    FIREBASE_AVAILABLE = True
except Exception as e:
    logger.info("Firebase module not available: %s", e)
    FIREBASE_AVAILABLE = False
    # Provide safe fallbacks for all Firebase functions used
    initialize_firebase = lambda: False
    firebase_login_ui = lambda: st.warning("Firebase login UI not available")
    firebase_signup_ui = lambda: st.warning("Firebase signup UI not available")
    firebase_password_recovery_ui = lambda: st.warning("Firebase password recovery not available")
    firebase_logout = lambda: None
    get_current_firebase_user = lambda: None
    check_firebase_user_role = lambda _user, _role: False
    init_sql_tables = lambda: None
    sync_users_from_firestore = lambda: []
    get_all_users = lambda: []
from firebase_auth_integration import sync_users_from_firestore as get_all_users
# Optional modules for other app sections
try:
    from kobo_integration import plant_a_tree_section, initialize_database
except Exception:
    plant_a_tree_section = lambda: st.warning("🌳 Tree planting section unavailable")
    initialize_database = lambda: None

try:
    from kobo_monitoring import monitoring_section, initialize_monitoring_db
except Exception:
    monitoring_section = lambda: st.warning("📊 Monitoring section unavailable")
    initialize_monitoring_db = lambda: None

try:
    from unified_user_dashboard_FINAL import unified_user_dashboard
except Exception:
    unified_user_dashboard = lambda: st.warning("👤 User dashboard unavailable")

try:
    from admin_dashboard import admin_dashboard
except Exception:
    admin_dashboard = lambda: st.warning("⚙️ Admin dashboard unavailable")

try:
    from field_agent_portal import field_agent_portal_ui
except Exception:
    field_agent_portal_ui = lambda: st.warning("🌍 Field agent portal unavailable")

try:
    from donor_dashboard import guest_donor_dashboard_ui
except Exception:
    guest_donor_dashboard_ui = lambda: st.warning("💰 Donor dashboard unavailable")


# ---------------------- SESSION STATE ----------------------
def initialize_session_state():
    defaults = {
        'authenticated': False,
        'page': 'Landing',
        'user': None,
        'field_agent_authenticated': False,
        'field_agent_tracking_number': None,
        'field_agent_name': None,
        'user_lat': None,
        'user_lon': None,
        'firebase_user': False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ---------------------- STYLES (MODERNIZED) ----------------------
def set_custom_css():
    st.markdown("""
    <style>
      :root { 
        --primary: #1D7749; 
        --primary-light: #28a745; 
        --secondary: #6c757d; 
        --light: #f8f9fa;
        --accent-green: #28a745;
      }
      /* Ensure full page use */
      .block-container {
          padding-top: 1rem; /* Reduced top padding */
          padding-bottom: 2rem;
          padding-left: 2rem;
          padding-right: 2rem;
      }
      
      /* Hero/Header Section */
      .landing-header {
          background: linear-gradient(135deg, var(--primary) 0%, var(--primary-light) 100%);
          color: white;
          padding: 2.5rem 1rem;
          border-radius: 12px; /* Modernized rounded corners */
          text-align: center;
          margin-bottom: 2rem;
          box-shadow: 0 4px 15px rgba(0,0,0,0.2); /* Soft shadow */
      }
      
      /* Section Header */
      .section-header {
          color: var(--primary);
          margin: 2rem 0 1rem;
          font-weight: 800;
          font-size: 1.8rem;
          border-bottom: 3px solid var(--primary-light);
          padding-bottom: 5px;
      }
      
      /* Metric Card - MODERN & PROFESSIONAL */
      .metric-card-modern {
          background: #fff;
          border-radius: 12px;
          padding: 1.5rem 1rem;
          box-shadow: 0 4px 10px rgba(0,0,0,0.1);
          text-align: left;
          margin-bottom: 1.5rem;
          transition: transform 0.2s, box-shadow 0.2s;
          border-left: 5px solid var(--accent-green); /* Accent line */
      }
      .metric-card-modern:hover {
          transform: translateY(-3px);
          box-shadow: 0 8px 15px rgba(0,0,0,0.15);
      }
      .metric-card-modern h3 {
          margin: 0;
          color: var(--secondary);
          font-size: 1rem;
          font-weight: 600;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
      }
      .metric-card-modern p {
          font-size: 2.2rem;
          margin: 0.5rem 0 0;
          font-weight: 900;
          color: var(--primary);
      }
      
      /* Recent Activity Card - MODERN LIST */
      .activity-card-modern {
          background: #fff;
          padding: 1rem;
          border-radius: 8px;
          margin-bottom: 1rem;
          box-shadow: 0 1px 4px rgba(0,0,0,0.05);
          border-left: 4px solid var(--accent-green);
          transition: background 0.1s;
      }
      .activity-card-modern:hover {
          background: #f0fff0;
      }
      .activity-card-modern strong {
          color: #333;
      }
      .activity-detail {
          color: var(--secondary);
          font-size: 0.9rem;
          margin-top: 4px;
          display: flex;
          gap: 10px;
      }
      
      /* Button Styling for Quick Access */
      .stButton>button {
          background-color: var(--primary) !important;
          color: white !important;
          font-weight: bold;
          border-radius: 8px;
          padding: 0.75rem 0;
          transition: background-color 0.2s;
      }
      .stButton>button:hover {
          background-color: var(--primary-light) !important;
      }
    </style>
    """, unsafe_allow_html=True)


# ---------------------- DATABASE HELPERS ----------------------
def get_db_connection():
    try:
        conn = sqlite3.connect(SQLITE_DB, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.exception("Failed to connect to DB: %s", e)
        st.error("Database connection error. See logs.")
        return None


def ensure_tables_exist():
    """Create minimal tables if they don't exist to avoid runtime errors."""
    conn = get_db_connection()
    if not conn:
        return
    try:
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            email TEXT,
            full_name TEXT,
            password_hash TEXT,
            status TEXT DEFAULT 'pending',
            role TEXT DEFAULT 'individual',
            tree_tracking_number TEXT,
            field_password TEXT,
            token_created_at INTEGER
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS trees (
            id INTEGER PRIMARY KEY,
            uid TEXT,
            local_name TEXT,
            scientific_name TEXT,
            date_planted TEXT,
            planters_name TEXT,
            latitude REAL,
            longitude REAL,
            status TEXT DEFAULT 'Alive',
            co2_kg REAL DEFAULT 0,
            treeTrackingNumber TEXT
        )
        """)

        conn.commit()
    except Exception as e:
        logger.exception("Error ensuring tables: %s", e)
    finally:
        conn.close()


# ---------------------- METRICS ----------------------
@st.cache_data(ttl=60)
def get_landing_metrics():
    conn = get_db_connection()
    if not conn:
        return {
            'institutions': 0, 'total_trees': 0, 'alive_trees': 0, 'survival_rate': 0, 'co2_sequestered': 0, 'map_data': pd.DataFrame()
        }
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(DISTINCT email) FROM users")
        institutions_count = c.fetchone()[0] or 0

        trees_df = pd.read_sql_query("SELECT * FROM trees", conn)
        total_trees = len(trees_df)
        alive_trees = int((trees_df['status'] == 'Alive').sum()) if 'status' in trees_df.columns else total_trees
        dead_trees = total_trees - alive_trees
        survival_rate = round((alive_trees / total_trees * 100), 1) if total_trees > 0 else 0
        co2 = float(trees_df['co2_kg'].sum()) if 'co2_kg' in trees_df.columns else 0

        map_data = trees_df[['latitude', 'longitude']].dropna() if not trees_df.empty else pd.DataFrame()

        return {
            'institutions': institutions_count,
            'total_trees': total_trees,
            'alive_trees': alive_trees,
            'survival_rate': survival_rate,
            'co2_sequestered': round(co2, 2),
            'map_data': map_data
        }
    except Exception as e:
        logger.exception("Error computing metrics: %s", e)
        return {'institutions': 0, 'total_trees': 0, 'alive_trees': 0, 'survival_rate': 0, 'co2_sequestered': 0, 'map_data': pd.DataFrame()}
    finally:
        conn.close()


# ---------------------- FIELD AGENT AUTH ----------------------
def field_agent_login_ui():
    set_custom_css()

    st.markdown("<div style='max-width:700px;margin:0 auto;padding:2rem;'>", unsafe_allow_html=True)
    st.header("🌍 Field Agent Access")
    st.write("Enter your organization's tree tracking number and field password.")

    with st.form("field_agent_login_form"):
        entered_tracking_number = st.text_input("Tree Tracking Number", key="fa_tracking_number")
        entered_password = st.text_input("Field Password", type="password", key="fa_password")
        login_button = st.form_submit_button("Login to Field Portal")

    if login_button:
        if not entered_tracking_number or not entered_password:
            st.error("Please enter both tracking number and password.")
            return
        success, message = authenticate_field_agent(entered_tracking_number.strip().upper(), entered_password.strip())
        if success:
            st.success("✅ Login successful!")
            st.session_state.page = "FieldAgentPortal"
            st.rerun() # Corrected: st.experimental_rerun() -> st.rerun()
        else:
            st.error(message)

    if st.button("← Back to Home"):
        st.session_state.page = "Landing"
        st.rerun() # Corrected: st.experimental_rerun() -> st.rerun()


def authenticate_field_agent(tracking_number: str, password: str):
    conn = get_db_connection()
    if not conn:
        return False, "Database connection failed"
    try:
        c = conn.cursor()
        c.execute("SELECT full_name, field_password, token_created_at, status FROM users WHERE (tree_tracking_number = ? OR treeTrackingNumber = ?) AND field_password IS NOT NULL", (tracking_number, tracking_number))
        row = c.fetchone()
        if not row:
            return False, "Invalid tracking number or no field password set"
            
        # Safely access keys based on row_factory=sqlite3.Row
        full_name = row['full_name'] if 'full_name' in row.keys() else None
        stored_password = row['field_password'] if 'field_password' in row.keys() else None
        token_created_at = row['token_created_at'] if 'token_created_at' in row.keys() else None
        status = row['status'] if 'status' in row.keys() else 'pending'

        if status != 'approved':
            return False, "Account not approved. Please contact administrator."

        if password != stored_password:
            return False, "Invalid password"

        if token_created_at and (int(time.time()) - int(token_created_at) > 86400):
            return False, "Password expired. Request a new one from account holder."

        st.session_state.field_agent_authenticated = True
        st.session_state.field_agent_tracking_number = tracking_number
        st.session_state.field_agent_name = full_name or f"Field Agent {tracking_number}"
        return True, "Authentication successful"
    except Exception as e:
        logger.exception("Field agent auth error: %s", e)
        return False, f"Authentication error: {e}"
    finally:
        conn.close()


# ---------------------- LANDING PAGE ----------------------

def show_landing_page():
    set_custom_css()
    ensure_tables_exist()

    metrics = get_landing_metrics()

    # --- HERO SECTION ---
    st.markdown("""
      <div class="landing-header">
        <h1 style="margin-bottom:0.3rem;">CarbonTally</h1>
        <p style="font-size:1.1rem;margin-top:0;">Track, monitor, and contribute to reforestation efforts worldwide</p>
      </div>
    """, unsafe_allow_html=True)

    # --- PROFESSIONAL METRIC CARDS (Heading removed) ---
    colA, colB, colC, colD = st.columns(4)

    # Tree Metric
    with colA:
        st.markdown(f"""
        <div class='metric-card-modern'>
            <h3 style='color:#1D7749;'>Trees Planted</h3>
            <p>{metrics['total_trees']:,}</p>
        </div>""",
        unsafe_allow_html=True)

    # Institution Metric
    with colB:
        st.markdown(f"""
        <div class='metric-card-modern'>
            <h3 style='color:#1D7749;'>Institutions</h3>
            <p>{metrics['institutions']:,}</p>
        </div>""",
        unsafe_allow_html=True)

    # CO2 Metric
    with colC:
        st.markdown(f"""
        <div class='metric-card-modern'>
            <h3 style='color:#1D7749;'>CO₂ Sequestered (kg)</h3>
            <p>{metrics['co2_sequestered']:,}</p>
        </div>""",
        unsafe_allow_html=True)

    # Survival Rate Metric
    with colD:
        st.markdown(f"""
        <div class='metric-card-modern'>
            <h3 style='color:#1D7749;'>Survival Rate</h3>
            <p>{metrics['survival_rate']}%</p>
        </div>""",
        unsafe_allow_html=True)
    
    # --- MAP SECTION (Heading removed) ---
    # We use a slight spacer instead of a header for visual separation
    st.markdown("<div style='height: 1.5rem;'></div>", unsafe_allow_html=True) 
    
    try:
        conn = get_db_connection()
        trees_df = pd.read_sql_query("""
            SELECT latitude, longitude, local_name as species,
                    strftime('%Y-%m-%d', date_planted) as date_planted,
                    planters_name, co2_kg
            FROM trees
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
            ORDER BY date_planted DESC
        """, conn)
        if not trees_df.empty:
            fig = px.scatter_mapbox(
                trees_df,
                lat="latitude",
                lon="longitude",
                hover_name="species",
                hover_data={"date_planted": True, "planters_name": True, "co2_kg": ":.2f"},
                zoom=1, height=500,
                color_discrete_sequence=["#1D7749"],
            )
            fig.update_layout(mapbox_style="open-street-map", margin={"r":0,"t":0,"l":0,"b":0})
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No tree location data available yet.")
    finally:
        if 'conn' in locals():
            conn.close()
    
    # --- ACTION BUTTONS (Heading removed, 2-column grid maintained) ---
    st.markdown("<div style='height: 1.5rem;'></div>", unsafe_allow_html=True) # Spacer

    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🔐 Log In (User Portal)", use_container_width=True):
            st.session_state.page = "Login"
            st.rerun() # Corrected: st.experimental_rerun() -> st.rerun()
    with col2:
        if st.button("🌍 Field Agent Portal", use_container_width=True):
            st.session_state.page = "FieldAgentLogin"
            st.rerun() # Corrected: st.experimental_rerun() -> st.rerun()

    col3, col4 = st.columns(2)
    with col3:
        if st.button("📝 Create Account", use_container_width=True):
            st.session_state.page = "Sign Up"
            st.rerun() # Corrected: st.experimental_rerun() -> st.rerun()
    with col4:
        if st.button("💚 Support Us (Donate)", use_container_width=True):
            st.session_state.page = "Donate"
            st.rerun() # Corrected: st.experimental_rerun() -> st.rerun()

    # --- RECENT ACTIVITY (Icon removed) ---
    st.markdown("<h3 class='section-header'>Recent Planting Activity</h3>", unsafe_allow_html=True)
    try:
        conn = get_db_connection()
        df = pd.read_sql_query("""
            SELECT planters_name, local_name, ROUND(co2_kg,2) as co2_kg,
                    strftime('%Y-%m-%d', date_planted) as formatted_date
            FROM trees
            WHERE date_planted IS NOT NULL
            ORDER BY date_planted DESC
            LIMIT 6
        """, conn)

        cols = st.columns(2)
        if not df.empty:
            for i, row in df.iterrows():
                card = f"""
                <div class='activity-card-modern'>
                    <strong>{row['planters_name']}</strong> planted a <strong>{row['local_name']}</strong>
                    <div class='activity-detail'>
                        <span>🌱 {row['co2_kg']} kg CO₂</span>
                        <span>📅 {row['formatted_date']}</span>
                    </div>
                </div>"""
                # Distribute cards between the two columns
                (cols[0] if i % 2 == 0 else cols[1]).markdown(card, unsafe_allow_html=True)
        else:
            st.info("No recent activity found.")
    finally:
        if 'conn' in locals():
            conn.close()


# ---------------------- SIDEBAR ----------------------

def show_sidebar():
    with st.sidebar:
        if isinstance(icon_setting, Image.Image):
             st.image(icon_setting, width=150)
        else:
             st.markdown("<h3 style='color:#1D7749;'>🌱 CarbonTally</h3>", unsafe_allow_html=True)
        
        st.markdown("---")
        
        if st.session_state.authenticated and st.session_state.user and st.session_state.get('firebase_user'):
            user_display_name = st.session_state.user.get('displayName', st.session_state.user.get('username', 'User'))
            st.markdown(f"**Welcome, {user_display_name}!**")
            user_role = st.session_state.user.get('role', 'individual')
            
            page_options = ["User Dashboard", "Plant a Tree", "Monitor Trees", "Donor Dashboard"]
            if user_role == 'admin':
                 page_options.insert(0, "Admin Dashboard")
                 
            try:
                idx = page_options.index(st.session_state.page)
            except ValueError:
                idx = 0
            
            st.session_state.page = st.radio("Navigate to:", page_options, index=idx)
            
            if st.button("Logout", use_container_width=True):
                if FIREBASE_AVAILABLE:
                    firebase_logout()
                st.session_state.authenticated = False
                st.session_state.user = None
                st.session_state.firebase_user = False
                st.session_state.page = "Landing"
                st.rerun() # Corrected: st.experimental_rerun() -> st.rerun()
        else:
            # Public choices
            options = ["Landing", "Login", "Sign Up", "Password Recovery", "Donor Dashboard"]
            try:
                idx = options.index(st.session_state.page)
            except ValueError:
                idx = 0
            st.session_state.page = st.radio("Choose an option:", options, index=idx)


# ---------------------- MAIN CONTENT ----------------------
def show_main_content():
    current_page = st.session_state.page
    
    # Handle public/login pages first
    if current_page == "Login" and FIREBASE_AVAILABLE:
        firebase_login_ui()
    elif current_page == "Sign Up" and FIREBASE_AVAILABLE:
        firebase_signup_ui()
    elif current_page == "Password Recovery" and FIREBASE_AVAILABLE:
        firebase_password_recovery_ui()
    elif current_page in ("Donate", "Donor Dashboard"):
        guest_donor_dashboard_ui()
    elif current_page == "Landing":
        show_landing_page()
    
    # Handle authenticated pages
    elif st.session_state.authenticated and st.session_state.get('firebase_user'):
        if current_page == "User Dashboard":
            unified_user_dashboard()
        elif current_page == "Admin Dashboard":
            admin_dashboard()
        elif current_page == "Plant a Tree":
            plant_a_tree_section()
        elif current_page == "Monitor Trees":
            monitoring_section()
        else:
            st.warning("Page not found. Redirecting to User Dashboard.")
            st.session_state.page = "User Dashboard"
            st.rerun() # Corrected: st.experimental_rerun() -> st.rerun()
    else:
        # Show a friendly login prompt for unauthorized access
        st.warning("🔒 Please log in to access this page")
        if FIREBASE_AVAILABLE:
            firebase_login_ui()

    st.markdown("---")
    st.markdown("<div style='text-align:center;color:gray;font-size:0.9rem;'>\n            <strong>CarbonTally</strong> | Making Every Tree Count 🌱<br>\n            © 2025 CarbonTally. All rights reserved.\n        </div>", unsafe_allow_html=True)


# ---------------------- APP ENTRY ----------------------

def main():
    initialize_session_state()
    ensure_tables_exist()

    if FIREBASE_AVAILABLE:
        if not initialize_firebase():
            st.error("Failed to initialize Firebase. Some features will be unavailable.")
        else:
            try:
                sync_users_from_firestore()
            except Exception:
                logger.exception("Failed to sync users from Firestore")

    # Initialize optional DBs
    try: initialize_database()
    except Exception: logger.info("No additional initialize_database function present or it failed")
    try: initialize_monitoring_db()
    except Exception: logger.info("No monitoring DB initializer present or it failed")

    # Routing
    if st.session_state.page == "Landing":
        show_landing_page()
    elif st.session_state.page == "FieldAgentLogin":
        field_agent_login_ui()
    elif st.session_state.page == "FieldAgentPortal" and st.session_state.field_agent_authenticated:
        field_agent_portal_ui()
    else:
        # All authenticated or public non-landing pages show the sidebar and content
        show_sidebar()
        show_main_content()


if __name__ == "__main__":
    main()
