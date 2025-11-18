# app.py - Complete Fixed Version with Firebase Authentication

import streamlit as st
from PIL import Image
from pathlib import Path
import sqlite3
import pandas as pd
import plotly.express as px
from datetime import datetime
import time

# ========== STREAMLIT CONFIG - MUST BE FIRST ==========
st.set_page_config(
    page_title="CarbonTally",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ========== IMPORTS WITH ERROR HANDLING ==========
def safe_import(module_name, function_name, fallback_function):
    """Safely import a function with fallback"""
    try:
        module = __import__(module_name, fromlist=[function_name])
        return getattr(module, function_name)
    except ImportError as e:
        st.error(f"⚠️ {module_name} not available: {e}")
        return fallback_function

# Fallback functions
def fallback_feature():
    st.warning("This feature is currently unavailable. Please check module imports.")
    return None

def fallback_dataframe():
    return pd.DataFrame()

# Import modules
try:
    from firebase_auth_integration import (
        initialize_firebase, firebase_login_ui, firebase_signup_ui,
        firebase_password_recovery_ui, firebase_logout, get_current_firebase_user,
        check_firebase_user_role, init_sql_tables, sync_users_from_firestore,
        get_all_users
    )
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    # Create fallback functions
    def initialize_firebase(): return False
    def firebase_login_ui(): st.warning("Login unavailable")
    def firebase_signup_ui(): st.warning("Signup unavailable")
    def firebase_password_recovery_ui(): st.warning("Password recovery unavailable")
    def firebase_logout(): pass
    def get_current_firebase_user(): return None
    def check_firebase_user_role(user, role): return False
    def init_sql_tables(): pass
    def sync_users_from_firestore(): pass
    def get_all_users(): return []

try:
    from kobo_integration import plant_a_tree_section, initialize_database
except ImportError:
    plant_a_tree_section = lambda: st.warning("🌳 Tree planting section unavailable")
    initialize_database = lambda: None

try:
    from kobo_monitoring import monitoring_section, initialize_monitoring_db
except ImportError:
    monitoring_section = lambda: st.warning("📊 Monitoring section unavailable")
    initialize_monitoring_db = lambda: None

try:
    from unified_user_dashboard_FINAL import unified_user_dashboard
except ImportError:
    unified_user_dashboard = lambda: st.warning("👤 User dashboard unavailable")

try:
    from admin_dashboard import admin_dashboard
except ImportError:
    admin_dashboard = lambda: st.warning("⚙️ Admin dashboard unavailable")

try:
    from field_agent import field_agent_portal
except ImportError:
    field_agent_portal = lambda: st.warning("🌍 Field agent portal unavailable")

try:
    from donor_dashboard import guest_donor_dashboard_ui
except ImportError:
    guest_donor_dashboard_ui = lambda: st.warning("💰 Donor dashboard unavailable")

# ========== PATHS & CONSTANTS ==========
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True, parents=True)
SQLITE_DB = DATA_DIR / "trees.db"

# ========== SESSION STATE INITIALIZATION ==========
def initialize_session_state():
    """Initialize all session state variables"""
    defaults = {
        'authenticated': False,
        'page': 'Landing',
        'user': None,
        'field_agent_authenticated': False,
        'field_agent_tracking_number': None,
        'field_agent_name': None,
        'user_lat': None,
        'user_lon': None,
        'firebase_user': False  # Add this to track Firebase authentication
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# ========== CUSTOM CSS ==========
def set_custom_css():
    st.markdown("""
    <style>
      :root {
        --primary: #1D7749;
        --primary-light: #28a745;
        --secondary: #6c757d;
        --light: #f8f9fa;
      }
      .app-header {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 60px;
        background-color: var(--primary);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 9999;
        box-shadow: 0 2px 6px rgba(0,0,0,0.2);
      }
      .app-header img {
        height: 40px;
        object-fit: contain;
      }
      .block-container {
        padding-top: 60px !important;
        padding-bottom: 1rem !important;
        max-width: 1200px;
      }
      .landing-header {
        background: linear-gradient(135deg, var(--primary) 0%, var(--primary-light) 100%);
        color: white;
        padding: 2.5rem 1rem;
        border-radius: 0 0 20px 20px;
        text-align: center;
        margin-bottom: 2rem;
      }
      .landing-header h1 {
        font-size: 3rem;
        margin: 0 0 0.25rem;
        font-weight: 800;
        text-shadow: 1px 1px 3px rgba(0,0,0,0.2);
      }
      .landing-header p {
        margin: 0.25rem 0;
        font-size: 1.1rem;
        opacity: 0.9;
      }
      .section-header {
        color: var(--primary);
        margin: 1.5rem 0 1rem;
        font-weight: 700;
        font-size: 1.6rem;
        position: relative;
        padding-bottom: 0.4rem;
      }
      .section-header:after {
        content: '';
        position: absolute;
        bottom: 0;
        left: 0;
        width: 50px;
        height: 3px;
        background: var(--primary);
        border-radius: 3px;
      }
      .metric-card {
        background: white;
        border-radius: 12px;
        padding: 1rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        text-align: center;
        margin-bottom: 0.75rem;
        transition: transform 0.3s;
      }
      .metric-card:hover {
        transform: translateY(-4px);
      }
      .metric-label {
        font-size: 0.85rem;
        color: var(--secondary);
        margin-bottom: 0.3rem;
        text-transform: uppercase;
        font-weight: 600;
      }
      .metric-value {
        font-size: 2rem;
        font-weight: 700;
        color: var(--primary);
        margin-bottom: 0.3rem;
      }
      .stButton > button,
      .stButton button {
        background-color: var(--primary) !important;
        color: white !important;
        padding: 0.6em 1.4em !important;
        font-size: 1rem !important;
        font-weight: 600 !important;
        border-radius: 0.4rem !important;
        box-shadow: 0 2px 6px rgba(0,0,0,0.15) !important;
        transition: background-color 0.2s ease, transform 0.1s ease !important;
      }
      .stButton > button:hover,
      .stButton button:hover {
        background-color: #166534 !important;
        transform: translateY(-1px) !important;
      }
      .feature-card, .activity-item {
        background: white;
        border-radius: 12px;
        padding: 1rem;
        box-shadow: 0 2px 6px rgba(0,0,0,0.05);
        margin-bottom: 1rem;
        transition: transform 0.3s, box-shadow 0.3s;
      }
      .feature-card:hover, .activity-item:hover {
        transform: translateY(-3px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
      }
      @media (max-width: 768px) {
        .landing-header {
          padding: 2rem 1rem;
        }
        .landing-header h1 {
          font-size: 2.5rem;
        }
        .metric-card {
          padding: 0.8rem;
        }
      }
    </style>
    """, unsafe_allow_html=True)

# ========== DATABASE FUNCTIONS ==========
def get_db_connection():
    """Get database connection"""
    try:
        return sqlite3.connect(SQLITE_DB)
    except Exception as e:
        st.error(f"Database connection error: {e}")
        return None

def get_landing_metrics():
    """Get current metrics for the landing page"""
    conn = get_db_connection()
    try:
        institutions_count = conn.execute("SELECT COUNT(*) FROM institutions").fetchone()[0]
        trees_df = pd.read_sql_query("SELECT * FROM trees", conn)
        dead_trees = len(trees_df[trees_df["status"] == "Dead"]) if "status" in trees_df.columns else 0
        total_trees = len(trees_df)
        survival_rate = round(((total_trees - dead_trees) / total_trees * 100), 1) if total_trees > 0 else 0

        metrics = {
            "institutions": institutions_count,
            "total_trees": total_trees,
            "alive_trees": total_trees - dead_trees,
            "survival_rate": survival_rate,
            "co2_sequestered": round(trees_df['co2_kg'].sum(), 2) if 'co2_kg' in trees_df.columns else 0,
            "map_data": trees_df[['latitude', 'longitude']].dropna() if not trees_df.empty else pd.DataFrame()
        }
        return metrics
    except Exception as e:
        st.error(f"Error loading metrics: {str(e)}")
        return {
            "institutions": 0,
            "total_trees": 0,
            "alive_trees": 0,
            "survival_rate": 0,
            "co2_sequestered": 0,
            "map_data": pd.DataFrame()
        }
    finally:
        conn.close()

# ========== DEBUG FUNCTIONS ==========
def debug_sqlite_users():
    """Debug function to see what users are in SQLite"""
    st.subheader("📊 SQLite Users Debug")
    
    conn = get_db_connection()
    if not conn:
        st.error("Cannot connect to SQLite database")
        return
    
    try:
        # Check users table structure
        c = conn.cursor()
        c.execute("PRAGMA table_info(users)")
        columns = c.fetchall()
        st.write("### Users Table Structure:")
        for col in columns:
            st.write(f"- {col[1]} ({col[2]})")
        
        # Show all users with their password hashes
        c.execute("SELECT username, email, password_hash, status FROM users")
        users = c.fetchall()
        
        st.write("### Users in SQLite:")
        if users:
            for user in users:
                st.write(f"**Username:** {user[0]}")
                st.write(f"**Email:** {user[1]}")
                st.write(f"**Password Hash:** `{user[2]}`")
                st.write(f"**Status:** {user[3]}")
                st.write("---")
        else:
            st.info("No users found in SQLite database")
            
    except Exception as e:
        st.error(f"SQLite debug error: {e}")
    finally:
        conn.close()

# ========== FIELD AGENT AUTHENTICATION ==========
def field_agent_login_ui():
    """Field agent login interface"""
    st.markdown("""
    <style>
        .field-agent-login-container {
            background-color: #f0f2f6;
            padding: 3rem;
            border-radius: 15px;
            box-shadow: 0 8px 20px rgba(0,0,0,0.1);
            max-width: 500px;
            margin: 3rem auto;
            text-align: center;
        }
        .field-agent-login-container h2 {
            color: #1D7749;
            margin-bottom: 1.5rem;
            font-size: 2.2rem;
            font-weight: 700;
        }
        .field-agent-login-container .stTextInput>div>div>input {
            border-radius: 8px;
            border: 1px solid #ced4da;
            padding: 0.75rem 1rem;
            font-size: 1rem;
        }
        .field-agent-login-container .stButton>button {
            background-color: #1D7749;
            color: white;
            border-radius: 8px;
            padding: 0.8rem 2rem;
            font-size: 1.1rem;
            font-weight: 600;
            transition: all 0.3s ease;
            width: 100%;
            margin-top: 1.5rem;
        }
        .field-agent-login-container .stButton>button:hover {
            background-color: #218838;
            transform: translateY(-2px);
            box-shadow: 0 4px 10px rgba(0,0,0,0.15);
        }
        .field-agent-login-container .stAlert {
            border-radius: 8px;
            margin-top: 1rem;
        }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="field-agent-login-container">
        <h2>🌍 Field Agent Access</h2>
        <p style="color: #6c757d; margin-bottom: 2rem;">Enter your organization's tree tracking number and field password.</p>
    </div>
    """, unsafe_allow_html=True)

    with st.form("field_agent_login_form"):
        entered_tracking_number = st.text_input("Tree Tracking Number", key="fa_tracking_number")
        entered_password = st.text_input("Field Password", type="password", key="fa_password")

        login_button = st.form_submit_button("Login to Field Portal")

        if login_button:
            if not entered_tracking_number or not entered_password:
                st.error("Please enter both tracking number and password.")
                return

            # Authenticate field agent
            success, message = authenticate_field_agent(
                entered_tracking_number.strip().upper(), 
                entered_password.strip().upper()
            )
            
            if success:
                st.success("✅ Login successful! Redirecting...")
                st.session_state.page = "FieldAgentPortal"
                st.rerun()
            else:
                st.error(f"❌ {message}")

    if st.button("← Back to Home", key="fa_back_to_home"):
        st.session_state.page = "Landing"
        st.rerun()

def authenticate_field_agent(tracking_number, password):
    """Authenticate field agent with tracking number and password"""
    conn = get_db_connection()
    if not conn:
        return False, "Database connection failed"
    
    try:
        c = conn.cursor()
        
        # Try both column names for compatibility
        c.execute("""
            SELECT full_name, field_password, token_created_at, status 
            FROM users 
            WHERE tree_tracking_number = ? AND field_password IS NOT NULL
        """, (tracking_number,))
        
        result = c.fetchone()
        
        if not result:
            # Try alternative column name
            c.execute("""
                SELECT full_name, field_password, token_created_at, status 
                FROM users 
                WHERE treeTrackingNumber = ? AND field_password IS NOT NULL
            """, (tracking_number,))
            result = c.fetchone()
            
            if not result:
                return False, "Invalid tracking number or no field password set"
        
        full_name, stored_password, token_created_at, status = result
        
        # Check if account is approved
        if status != 'approved':
            return False, "Account not approved. Please contact administrator."
        
        # Check password match
        if password != stored_password:
            return False, "Invalid password"
        
        # Check if password is expired (24 hours)
        current_time = int(time.time())
        if token_created_at and (current_time - token_created_at > 86400):
            return False, "Password has expired. Please request a new one from the account holder."
        
        # Set session state
        st.session_state.field_agent_authenticated = True
        st.session_state.field_agent_tracking_number = tracking_number
        st.session_state.field_agent_name = full_name or f"Field Agent {tracking_number}"
        
        return True, "Authentication successful"
        
    except Exception as e:
        return False, f"Authentication error: {e}"
    finally:
        conn.close()

# ========== LANDING PAGE ==========
def show_landing_page():
    """Main landing page"""
    set_custom_css()
    metrics = get_landing_metrics()

    # Logo & Hero
    logo_path = Path(r"D:\CARBONTALLY\carbontallyfinalized\CarbonTally-main\assets\default_logo.png")
    if logo_path.exists():
        st.image(str(logo_path), width=180, use_container_width=False)

    st.markdown("""
      <div class="landing-header">
        <h1>CarbonTally</h1>
        <p>Track, monitor, and contribute to reforestation efforts worldwide</p>
        <p>Join our mission to combat climate change one tree at a time.</p>
      </div>
    """, unsafe_allow_html=True)

    # System Overview Metrics
    st.markdown("""
    <style>
    .metric-card {
      background-color: #f4f6f8;
      padding: 1rem;
      border-left: 5px solid #27ae60;
      border-radius: 10px;
      box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .metric-title { color: #7f8c8d; font-weight: 600; }
    .metric-value { color: #2c3e50; font-size: 1.8rem; font-weight: 700; }
    </style>
    """, unsafe_allow_html=True)

    st.subheader("🌍 System Overview")
    cols = st.columns(4)

    with cols[0]:
        st.markdown("""
        <div class='metric-card'>
            <div class='metric-title'>🌱 Trees Planted</div>
            <div class='metric-value'>{:,}</div>
        </div>
        """.format(metrics['total_trees']), unsafe_allow_html=True)

    with cols[1]:
        st.markdown("""
        <div class='metric-card'>
            <div class='metric-title'>👥 Participating Entities</div>
            <div class='metric-value'>{:,}</div>
        </div>
        """.format(metrics['institutions']), unsafe_allow_html=True)

    with cols[2]:
        st.markdown("""
        <div class='metric-card'>
            <div class='metric-title'>💨 CO₂ Sequestered</div>
            <div class='metric-value'>{:,.2f} kg</div>
        </div>
        """.format(metrics['co2_sequestered']), unsafe_allow_html=True)

    with cols[3]:
        st.markdown("""
        <div class='metric-card'>
            <div class='metric-title'>🌿 Survival Rate</div>
            <div class='metric-value'>{:,.1f}%</div>
        </div>
        """.format(metrics['survival_rate']), unsafe_allow_html=True)

    # Tree Planting Locations Map
    st.markdown('<div class="section-header">🌳 Tree Planting Locations</div>', unsafe_allow_html=True)
    
    try:
        # Get tree data with coordinates
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
            # Create the map visualization
            fig = px.scatter_mapbox(
                trees_df,
                lat="latitude",
                lon="longitude",
                hover_name="species",
                hover_data={
                    "latitude": False,
                    "longitude": False,
                    "date_planted": True,
                    "planters_name": True,
                    "co2_kg": ":.2f",
                    "species": True
                },
                color_discrete_sequence=["#1D7749"],
                zoom=1,
                height=500
            )
            
            # Customize the map layout
            fig.update_layout(
                mapbox_style="open-street-map",
                margin={"r":0,"t":0,"l":0,"b":0},
                hoverlabel=dict(
                    bgcolor="white",
                    font_size=12,
                    font_family="Arial"
                )
            )
            
            # Show the map in Streamlit
            st.plotly_chart(fig, use_container_width=True)
            
            # Add some statistics below the map
            st.markdown(f"""
            <div style="background-color: #f8f9fa; padding: 1rem; border-radius: 8px; margin-top: -1rem;">
                <p style="margin: 0; font-size: 0.9rem;">
                    <strong>{len(trees_df):,}</strong> trees plotted from <strong>{trees_df['planters_name'].nunique():,}</strong> different planters.
                    Each green dot represents a tree planted.
                </p>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info("No tree location data available yet. Check back soon!")
            
    except Exception as e:
        st.error(f"Could not load tree location data: {str(e)}")
    finally:
        if 'conn' in locals():
            conn.close()

    # Login / Signup / Field-Agent / Donate buttons
    col1, col2 = st.columns(2, gap="small")
    with col1:
        if st.button("Log In to Your Account", key="landing_login", use_container_width=True):
            st.session_state.page = "Login"
            st.rerun()
        if st.button("Field Agent Portal", key="landing_field_agent", use_container_width=True):
            st.session_state.page = "FieldAgentLogin"
            st.rerun()

    with col2:
        if st.button("Create New Account", key="landing_signup", use_container_width=True):
            st.session_state.page = "Sign Up"
            st.rerun()
        if st.button("Support Our Mission", key="landing_donate", use_container_width=True):
            st.session_state.page = "Donate"
            st.rerun()

    # Recent Activity
    st.markdown('<div class="section-header">🔔 Recent Activity Feed</div>', unsafe_allow_html=True)

    try:
        with sqlite3.connect(SQLITE_DB) as conn:
            df = pd.read_sql_query("""
                SELECT 
                    planters_name, 
                    local_name, 
                    ROUND(co2_kg, 2) as co2_kg,
                    strftime('%Y-%m-%d', date_planted) as formatted_date
                FROM trees 
                WHERE date_planted IS NOT NULL
                ORDER BY date_planted DESC 
                LIMIT 6
            """, conn)

        if not df.empty:
            col1, col2 = st.columns(2)
            for i, row in df.iterrows():
                activity_html = f"""
                <div class="activity-item">
                    <div class="activity-content">
                        <span class="activity-highlight">{row['planters_name']}</span> planted a 
                        <span class="activity-highlight">{row['local_name']}</span> tree
                    </div>
                    <div class="activity-meta">
                        🌱 {row['co2_kg']} kg CO₂ • 📅 {row['formatted_date']}
                    </div>
                </div>
                """
                if i < 3:
                    with col1:
                        st.markdown(activity_html, unsafe_allow_html=True)
                else:
                    with col2:
                        st.markdown(activity_html, unsafe_allow_html=True)
        else:
            st.info("No recent activity found. Be the first to plant a tree!")

    except sqlite3.Error as e:
        st.error(f"Database error: {str(e)}")
    except Exception as e:
        st.error(f"Couldn't load recent activities: {str(e)}")

# ========== SIDEBAR NAVIGATION ==========
def show_sidebar():
    """Show sidebar navigation - Simplified for Firebase auth only"""
    with st.sidebar:
        st.markdown("<h3 style='color: #1D7749; margin-bottom: 1rem;'>🌱 CarbonTally</h3>", unsafe_allow_html=True)

        # DEBUG: Show authentication state
        with st.expander("🔧 Debug Info", expanded=False):
            st.write(f"**Page:** {st.session_state.page}")
            st.write(f"**Authenticated:** {st.session_state.authenticated}")
            st.write(f"**Firebase User:** {st.session_state.get('firebase_user', False)}")
            st.write(f"**User:** {st.session_state.user}")
            if st.button("Check SQLite Users"):
                debug_sqlite_users()

        if st.session_state.authenticated and st.session_state.user and st.session_state.get('firebase_user'):
            # Authenticated user sidebar
            user_display_name = st.session_state.user.get('displayName', st.session_state.user.get('username', 'User'))
            st.markdown(f"**Welcome, {user_display_name}!**")

            # Check user role from Firebase data
            user_role = st.session_state.user.get('role', 'individual')
            
            if user_role == 'admin':
                page_options = ["Admin Dashboard", "User Dashboard", "Plant a Tree", "Monitor Trees", "Donor Dashboard"]
            else:
                page_options = ["User Dashboard", "Plant a Tree", "Monitor Trees", "Donor Dashboard"]

            try:
                current_page_index = page_options.index(st.session_state.page)
            except ValueError:
                current_page_index = 0

            st.session_state.page = st.radio("Navigate to:", page_options, index=current_page_index)

            if st.button("Logout", use_container_width=True, type="primary"):
                # Firebase logout
                if FIREBASE_AVAILABLE:
                    firebase_logout()
                st.session_state.authenticated = False
                st.session_state.user = None
                st.session_state.firebase_user = False
                st.session_state.page = "Landing"
                st.rerun()
        else:
            # Public sidebar - Only Firebase options
            st.session_state.page = st.radio(
                "Choose an option:",
                ["Login", "Sign Up", "Password Recovery", "Donor Dashboard"],
                index=(["Login", "Sign Up", "Password Recovery", "Donor Dashboard"]
                       .index(st.session_state.page)
                       if st.session_state.page in ["Login", "Sign Up", "Password Recovery", "Donor Dashboard"] else 0)
            )

# ========== MAIN CONTENT ==========
def show_main_content():
    """Show main content based on current page - Firebase auth only"""
    current_page = st.session_state.page
    
    if current_page == "Login" and FIREBASE_AVAILABLE:
        firebase_login_ui()
    
    elif current_page == "Sign Up" and FIREBASE_AVAILABLE:
        firebase_signup_ui()
    
    elif current_page == "Password Recovery" and FIREBASE_AVAILABLE:
        firebase_password_recovery_ui()
    
    elif current_page == "Donate" or current_page == "Donor Dashboard":
        guest_donor_dashboard_ui()
    
    elif st.session_state.authenticated and st.session_state.get('firebase_user'):
        # User is authenticated via Firebase
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
            st.rerun()
    
    else:
        st.warning("🔒 Please log in to access this page")
        if FIREBASE_AVAILABLE:
            firebase_login_ui()
    
    # Footer
    st.markdown("---")
    st.markdown("""
        <div style='text-align: center; font-size: 0.9rem; color: gray;'>
            <strong>CarbonTally</strong> | Making Every Tree Count 🌱<br>
            Developed by <a href="mailto:okothbasil45@gmail.com">Basil Okoth</a> |
            <a href="https://www.linkedin.com/in/kaudobasil/" target="_blank">LinkedIn</a><br>
            © 2025 CarbonTally. All rights reserved.
        </div>
    """, unsafe_allow_html=True)

# ========== MAIN APPLICATION ==========
def main():
    """Main application controller"""
    # Initialize session state
    initialize_session_state()
    
    # Initialize Firebase if available
    if FIREBASE_AVAILABLE:
        if not initialize_firebase():
            st.error("❌ Failed to initialize Firebase. Some features may be unavailable.")
    
    # Initialize databases
    if initialize_database:
        initialize_database()
    if initialize_monitoring_db:
        initialize_monitoring_db()
    
    # Sync users for data purposes (not for authentication)
    if FIREBASE_AVAILABLE:
        sync_users_from_firestore()
    
    # SIMPLIFIED: Remove all auto-authentication logic
    # Users must explicitly login through the Firebase login form
    
    # Handle page routing
    if st.session_state.page == "Landing":
        show_landing_page()
    
    elif st.session_state.page == "FieldAgentLogin":
        field_agent_login_ui()
    
    elif st.session_state.page == "FieldAgentPortal" and st.session_state.field_agent_authenticated:
        field_agent_portal()
    
    else:
        # For other pages, show sidebar navigation
        show_sidebar()
        show_main_content()

# ========== ENTRY POINT ==========
if __name__ == "__main__":
    main()
