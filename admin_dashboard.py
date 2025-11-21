import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import altair as alt
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# NOTE: The imported modules below are assumed to be defined in your project.
from firebase_auth_integration import (
    get_all_users,
    sync_users_from_firestore,
    approve_user, reject_user, delete_user,
    send_approval_email, send_rejection_email
)
from firebase_auth_integration import sync_users_from_firestore as get_all_users
# Assuming this module/function exists and handles dependencies internally
from kobo_integration import generate_qr_code 

# ——— Paths & Configuration ———
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(exist_ok=True, parents=True) # Ensure data directory exists
SQLITE_DB = DATA_DIR / 'trees.db'
MONITORING_DB_PATH = DATA_DIR / 'monitoring.db'
ST_THEME_COLOR = "#1D7749" # Forest Green

# ——— Helper Functions (Unchanged from original) ———
def get_trees_db_connection():
    # Defensive programming: ensure the database file path is a string for sqlite3.connect
    return sqlite3.connect(str(SQLITE_DB))

def get_monitoring_db_connection():
    try:
        return sqlite3.connect(str(MONITORING_DB_PATH))
    except sqlite3.Error as e:
        logger.error(f"Monitoring DB error: {e}")
        return None

def get_total_trees_planted():
    conn = get_trees_db_connection()
    try:
        return pd.read_sql_query("SELECT COUNT(*) FROM trees", conn).iloc[0, 0]
    except:
        return 0
    finally:
        conn.close()

def get_total_users():
    conn = get_trees_db_connection()
    try:
        return pd.read_sql_query("SELECT COUNT(*) FROM users", conn).iloc[0, 0]
    except:
        return 0
    finally:
        conn.close()

def get_total_carbon_sequestered():
    conn = get_monitoring_db_connection()
    if not conn: return 0.0
    try:
        # Assuming the 'co2_kg' column exists in 'tree_monitoring' table
        result = pd.read_sql_query("SELECT SUM(co2_kg) FROM tree_monitoring", conn).iloc[0, 0]
        # Use result if it's not None, otherwise 0.0
        return result if result else 0.0
    except Exception as e:
        logger.warning(f"Error calculating carbon sequestration (monitoring.db might be empty or table missing): {e}")
        return 0.0
    finally:
        conn.close()

def get_survival_rate():
    total_trees = get_total_trees_planted()
    if total_trees == 0: return 0.0
    conn = get_monitoring_db_connection()
    if not conn: return 0.0
    try:
        # Placeholder logic: using count of monitored unique trees as a proxy for survival
        monitored = pd.read_sql_query("SELECT COUNT(DISTINCT tree_id) FROM tree_monitoring", conn).iloc[0, 0]
        return (monitored / total_trees) * 100
    except Exception as e:
        logger.warning(f"Error calculating survival rate: {e}")
        return 0.0
    finally:
        conn.close()

def get_user_trees_count(tracking_number):
    if not tracking_number: return 0
    conn = get_trees_db_connection()
    try:
        # Ensure tracking_number is treated as string for query
        return pd.read_sql_query(
            "SELECT COUNT(*) FROM trees WHERE treeTrackingNumber = ?", conn, params=(str(tracking_number),)
        ).iloc[0,0]
    except:
        return 0
    finally:
        conn.close()

def remove_user_from_sqlite_only(user_id, tracking_number):
    try:
        conn = get_trees_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE uid = ?", (user_id,))
        cur.execute("DELETE FROM pending_users WHERE uid = ?", (user_id,))
        trees_deleted = 0
        if tracking_number:
            cur.execute("DELETE FROM trees WHERE treeTrackingNumber = ?", (tracking_number,))
            trees_deleted = cur.rowcount
        conn.commit()
        return True, f"Removed user and {trees_deleted} trees from SQLite"
    except Exception as e:
        logger.error(f"Error removing user from SQLite: {e}")
        return False, str(e)
    finally:
        conn.close()

def debug_user_databases(user_email):
    debug_info = []
    conn = get_trees_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT uid, email, treeTrackingNumber FROM users WHERE email=?", (user_email,))
        user = cur.fetchone()
        if user: debug_info.append(f"✅ Found in SQLite users: UID={user[0]}, Tracking={user[2]}")
        else: debug_info.append("❌ Not in SQLite users")
        cur.execute("SELECT uid, email FROM pending_users WHERE email=?", (user_email,))
        pending = cur.fetchone()
        if pending: debug_info.append(f"✅ Found in pending_users: UID={pending[0]}")
        else: debug_info.append("❌ Not in pending_users")
        if user and len(user) > 2 and user[2]:
             debug_info.append(f"🌳 User has {get_user_trees_count(user[2])} trees (T.N. {user[2]})")
    except Exception as e:
        debug_info.append(f"❌ SQLite error: {e}")
    finally:
        conn.close()
    return debug_info

def remove_user_completely(user_data):
    tree_count = get_user_trees_count(user_data.get('treeTrackingNumber'))
    if tree_count > 0:
        return False, f"Cannot remove: user has {tree_count} trees."
    success, msg = remove_user_from_sqlite_only(user_data['uid'], user_data.get('treeTrackingNumber'))
    try:
        # Assumes delete_user handles Firebase/Firestore removal
        delete_user(user_data['uid'])
    except Exception as e:
        logger.error(f"Error deleting user from Firebase: {e}")
        pass
    return success, msg

def force_remove_user(user_data):
    tree_count = get_user_trees_count(user_data.get('treeTrackingNumber'))
    # SQLite removal (including trees)
    remove_user_from_sqlite_only(user_data['uid'], user_data.get('treeTrackingNumber'))
    try:
        # Firebase/Firestore removal
        delete_user(user_data['uid'])
    except Exception as e:
        logger.error(f"Error deleting user from Firebase: {e}")
        pass
    return True, f"Force removed user and {tree_count} trees."

# --- Chart Placeholder Functions ---
# Generate dummy data for the charts for demonstration
def generate_planting_trend_data():
    dates = [datetime.now() - timedelta(days=i) for i in range(30)]
    trees = np.random.randint(50, 200, 30)
    df = pd.DataFrame({
        'Date': dates,
        'Trees Planted': trees
    })
    return df.sort_values('Date')

def generate_species_data():
    species = ['Oak', 'Maple', 'Pine', 'Birch', 'Sequoia', 'Redwood', 'Palm']
    counts = np.random.randint(500, 5000, len(species))
    df = pd.DataFrame({
        'Species': species,
        'Count': counts
    })
    return df.sort_values('Count', ascending=False)

# ——— Dashboard ———
def admin_dashboard():
    # 1. Apply professional styling
    st.markdown(f"""
        <style>
            .main-header {{
                color: {ST_THEME_COLOR};
                font-weight: 700;
                margin-bottom: 20px;
                padding-left: 10px;
            }}
            .metric-card {{
                background-color: #f7f9fc; /* Light background for cards */
                border-left: 5px solid {ST_THEME_COLOR};
                border-radius: 8px;
                padding: 15px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
                margin-bottom: 20px;
            }}
            .metric-label {{
                font-size: 0.9rem;
                color: #6c757d;
                font-weight: 500;
            }}
            .metric-value {{
                font-size: 1.8rem;
                font-weight: 700;
                color: #212529;
                margin-top: 5px;
            }}
            .stTabs [data-baseweb="tab-list"] {{
                gap: 20px;
            }}
            .stTabs [data-baseweb="tab"] {{
                font-size: 1.1rem;
                font-weight: 600;
                color: #6c757d;
                border-radius: 6px;
                padding: 10px 15px;
            }}
            .stTabs [aria-selected="true"] {{
                color: {ST_THEME_COLOR};
                border-bottom: 3px solid {ST_THEME_COLOR};
            }}
            div[data-testid="stDataFrame"] {{
                border-radius: 8px;
                overflow: hidden;
            }}
        </style>
    """, unsafe_allow_html=True)

    st.markdown('<h1 class="main-header">🌳 CarbonTally Admin Portal</h1>', unsafe_allow_html=True)
    
    # --- Fetch ALL users once ---
    try:
        all_users = get_all_users()
    except Exception as e:
        logger.error(f"Error fetching all users: {e}")
        st.error("Could not load user data. Check `firebase_auth_integration` module.")
        all_users = []

    # Get approved count defensively
    approved_users_count = len([u for u in all_users if u.get('status') == 'approved'])

    # 2. Executive KPIs (Modern Metric Cards)
    total_trees = get_total_trees_planted()
    total_users = get_total_users() # This counts users in the SQL 'users' table (approved or otherwise)
    total_carbon = get_total_carbon_sequestered()
    survival_rate = get_survival_rate()

    col1, col2, col3, col4 = st.columns(4)

    # Note: Use st.metric for better integration, but preserving your custom HTML for style
    with col1:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">TOTAL TREES</div>
                <div class="metric-value">{total_trees:,}</div>
                <div style="font-size: 0.8rem; color: #28a745;">+1.2% this month</div>
            </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">REGISTERED AGENTS</div>
                <div class="metric-value">{total_users:,}</div>
                <div style="font-size: 0.8rem; color: #007bff;">{approved_users_count} Approved</div>
            </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">CO₂ OFFSET (KG)</div>
                <div class="metric-value">{total_carbon:,.0f}</div>
                <div style="font-size: 0.8rem; color: {ST_THEME_COLOR};">Goal: 10M kg</div>
            </div>
        """, unsafe_allow_html=True)

    with col4:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">SURVIVAL RATE</div>
                <div class="metric-value">{survival_rate:.1f}%</div>
                <div style="font-size: 0.8rem; color: #ffc107;">Needs Monitoring</div>
            </div>
        """, unsafe_allow_html=True)

    # 3. Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🌳 Tree Inventory",
        "👥 User Management",
        "📊 Analytics & Trends",
        "🔍 Tree Lookup",
        "🐛 Debug Users"
    ])

    # ----------------------------------------------------
    # --- Tab 1: Tree Management (Inventory) ---
    # ----------------------------------------------------
    with tab1:
        st.subheader("Complete Tree Inventory")
        try:
            conn = get_trees_db_connection()
            # Fetch essential columns for a compact view
            trees_df = pd.read_sql_query("SELECT tree_id, local_name, scientific_name, planters_name, treeTrackingNumber, latitude, longitude, date_planted FROM trees", conn)
        except Exception as e:
            logger.error(f"Error fetching tree inventory: {e}")
            trees_df = pd.DataFrame()
            st.error("Could not fetch tree data. Check the `trees` table.")
        finally:
            conn.close()

        if trees_df.empty:
            st.info("No trees found in the database.")
        else:
            st.dataframe(trees_df, use_container_width=True)
            st.download_button(
                label="⬇️ Download Full Tree Data (CSV)",
                data=trees_df.to_csv(index=False).encode(),
                file_name="carbontally_trees_inventory.csv",
                mime="text/csv"
            )

    # ----------------------------------------------------
    # --- Tab 2: User Management (Professional Table View) ---
    # ----------------------------------------------------
    with tab2:
        st.header("Field Agent Management")
        st.info("User statuses reflect data stored in SQLite. Click 'Sync' to update from Firebase/Firestore.")
        
        if st.button("🔄 Sync Users from Firebase", key="sync_btn_user_tab", type="primary"):
            sync_users_from_firestore()
            # Delay to allow sync to complete before fetching
            time.sleep(1) 
            st.success("User list synced successfully. Rerunning...")
            st.rerun()

        # Re-filter and prepare data from the freshly synced 'all_users' list
        pending = [u for u in all_users if u.get('status') == 'pending']
        approved_and_managed = [u for u in all_users if u.get('status') in ['approved', 'rejected']]

        # --- Pending Users ---
        st.markdown("#### ⏳ Pending Approvals")
        if pending:
            # Prepare data for DataFrame with defensive key access
            pending_data = []
            for u in pending:
                timestamp = u.get('createdAt') # Assuming 'createdAt' is the key for join date/timestamp
                
                # Robust timestamp conversion (assuming epoch time or Firestore timestamp object)
                if isinstance(timestamp, (int, float)) and timestamp > 0:
                     date_joined = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')
                elif isinstance(timestamp, datetime):
                     date_joined = timestamp.strftime('%Y-%m-%d %H:%M')
                else:
                    date_joined = 'N/A'

                pending_data.append({
                    'email': u.get('email', 'N/A'),
                    'name': u.get('fullName', 'N/A'), # Using 'fullName' as it's the expected key from previous code
                    'tracking_number': u.get('treeTrackingNumber', 'N/A'),
                    'Date Joined': date_joined,
                    'uid': u.get('uid')
                })
            
            pending_df = pd.DataFrame(pending_data)
            
            # Display pending users
            st.dataframe(pending_df[['email', 'name', 'tracking_number', 'Date Joined']], use_container_width=True)

            # Action section for pending users
            st.markdown("---")
            st.markdown("##### Action Pending Agents")
            
            selected_pending_email = st.selectbox(
                "Select Agent to Approve/Reject",
                options=pending_df['email'].tolist(),
                key="pending_select"
            )
            
            if selected_pending_email:
                # Retrieve the full user dict for the selected email
                u = next((item for item in pending_data if item['email'] == selected_pending_email), None)
                if u and u.get('uid'):
                    col_app, col_rej = st.columns(2)
                    with col_app:
                        if st.button(f"✅ Approve {u['name']}", key=f"app_{u['uid']}", type="primary", use_container_width=True):
                            approve_user(u['uid'])
                            send_approval_email(u) # NOTE: send_approval_email expects a dict with 'email', 'fullName', 'treeTrackingNumber'
                            st.success(f"{u['email']} approved. Rerunning...")
                            st.rerun()
                    with col_rej:
                        if st.button(f"🚫 Reject {u['name']}", key=f"rej_{u['uid']}", use_container_width=True):
                            reject_user(u['uid'])
                            send_rejection_email(u)
                            st.warning(f"{u['email']} rejected. Rerunning...")
                            st.rerun()
                else:
                    st.error("Selected user data is incomplete (missing UID). Please sync again.")
        else:
            st.info("🎉 No pending user signups.")

        # --- Approved/Managed Users ---
        st.markdown("#### ✅ Approved & Managed Agents")
        if approved_and_managed:
            # Prepare data for DataFrame with defensive key access
            approved_data = []
            for u in approved_and_managed:
                tracking_number = u.get('treeTrackingNumber')
                tree_count = get_user_trees_count(tracking_number)
                timestamp = u.get('createdAt') 
                
                if isinstance(timestamp, (int, float)) and timestamp > 0:
                     date_joined = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')
                elif isinstance(timestamp, datetime):
                     date_joined = timestamp.strftime('%Y-%m-%d %H:%M')
                else:
                    date_joined = 'N/A'

                approved_data.append({
                    'email': u.get('email', 'N/A'),
                    'name': u.get('fullName', 'N/A'), 
                    'tracking_number': tracking_number,
                    'Trees': tree_count,
                    'Date Joined': date_joined,
                    'status': u.get('status', 'unknown'),
                    'uid': u.get('uid')
                })
            
            approved_df = pd.DataFrame(approved_data)
            
            display_cols = ['email', 'name', 'tracking_number', 'Trees', 'Date Joined', 'status']
            st.dataframe(approved_df[display_cols], use_container_width=True)
            
            # Action section for approved users
            st.markdown("---")
            st.markdown("##### Remove or Force Remove Agents")
            
            selected_approved_email = st.selectbox(
                "Select Agent to Remove",
                options=approved_df['email'].tolist(),
                key="approved_select"
            )

            if selected_approved_email:
                # Retrieve the full user dict for the selected email
                u = approved_df[approved_df['email'] == selected_approved_email].iloc[0].to_dict()
                tree_count = u['Trees']

                col_rem, col_force = st.columns(2)

                with col_rem:
                    # Disable standard remove if user has trees
                    is_disabled = (tree_count > 0)
                    if st.button(f"🗑️ Remove User", key=f"rem_{u['uid']}", disabled=is_disabled, use_container_width=True):
                        success, msg = remove_user_completely(u)
                        if success:
                            st.success(f"User {u['email']} removed. Rerunning...")
                            st.rerun()
                        else:
                            st.error(f"Removal failed: {msg}")
                    if is_disabled:
                        st.caption(f"Cannot remove: Agent has **{tree_count}** trees recorded.")

                with col_force:
                    # Force Removal button
                    if st.button(f"🚨 Force Remove (Deletes {tree_count} Trees)", key=f"force_{u['uid']}", use_container_width=True):
                        # Confirmation step required for force removal
                        if st.confirm("DANGER: Force Removal will also delete all associated tree records (SQLite and Firebase). Proceed?"):
                            success, msg = force_remove_user(u)
                            if success:
                                st.success(f"User {u['email']} and {tree_count} trees force removed. Rerunning...")
                                st.rerun()
                            else:
                                st.error(f"Force removal failed: {msg}")

        else:
            st.info("No approved or managed agents to display.")

    # ----------------------------------------------------
    # --- Tab 3: Analytics (Professional Charts) ---
    # ----------------------------------------------------
    with tab3:
        st.header("Data Analytics and Trends")
        st.markdown("Visualizing key metrics for international reporting.")
        

        col_trend, col_species = st.columns(2)

        # Planting Trend Chart
        with col_trend:
            st.subheader("Daily Planting Volume (Last 30 Days)")
            trend_data = generate_planting_trend_data()
            chart = alt.Chart(trend_data).mark_line(point=True, color=ST_THEME_COLOR).encode(
                x=alt.X('Date', axis=alt.Axis(title='Date', format="%b %d")),
                y=alt.Y('Trees Planted', axis=alt.Axis(title='Trees Planted')),
                tooltip=['Date', 'Trees Planted']
            ).properties(
                height=300
            ).interactive()
            st.altair_chart(chart, use_container_width=True)

        # Species Distribution Chart
        with col_species:
            st.subheader("Top 10 Species Distribution")
            species_data = generate_species_data().head(10)
            chart = alt.Chart(species_data).mark_bar(color=ST_THEME_COLOR).encode(
                y=alt.Y('Species', sort='-x', title='Tree Species'),
                x=alt.X('Count', title='Total Count'),
                tooltip=['Species', 'Count']
            ).properties(
                height=300
            ).interactive()
            st.altair_chart(chart, use_container_width=True)

        # Placeholder for Map or Health Status
        st.subheader("Global Project Health Summary")
        st.info("Placeholder for a global map showing project site locations or a detailed health status breakdown (e.g., Survival Rate by Region).")


    # ----------------------------------------------------
    # --- Tab 4: Tree Lookup ---
    # ----------------------------------------------------
    with tab4:
        st.header("Tree and Monitoring Lookup")
        search = st.text_input("Search by Tree ID, Local Name, or Scientific Name")
        try:
            conn = get_trees_db_connection()
            trees_df_search = pd.read_sql_query("SELECT * FROM trees", conn)
        except Exception as e:
            logger.error(f"Error fetching tree lookup data: {e}")
            trees_df_search = pd.DataFrame()
        finally:
            conn.close()

        if search and not trees_df_search.empty:
            # Case-insensitive search across all string columns
            results = trees_df_search[
                trees_df_search.apply(lambda row: row.astype(str).str.contains(search, case=False, na=False).any(), axis=1)
            ]
            
            if not results.empty:
                st.dataframe(results[['tree_id', 'local_name', 'scientific_name', 'latitude', 'longitude', 'treeTrackingNumber']], use_container_width=True)
                
                # Ensure the selection options are strings for the selectbox
                selected_tree_id_str = st.selectbox("Select Tree ID for Details", results['tree_id'].astype(str).tolist())
                
                if selected_tree_id_str:
                    # Convert the string ID back to the type used in the DataFrame filter (often int)
                    selected_tree_id = int(selected_tree_id_str) 
                    
                    tree_data = results[results['tree_id']==selected_tree_id].iloc[0].to_dict()
                    
                    st.markdown("##### Tree Details")
                    st.json(tree_data)
                    
                    # Generate and display QR Code
                    st.markdown("##### QR Code for Monitoring")
                    qr_path = generate_qr_code(tree_id=tree_data['tree_id'], treeTrackingNumber=tree_data.get('treeTrackingNumber'))
                    
                    # NOTE: Assuming generate_qr_code returns a path or bytes Streamlit can display
                    if qr_path:
                         st.image(qr_path, caption=f"QR Code for Tree {tree_data['tree_id']}")
                    else:
                         st.warning("Could not generate QR code.")
            else:
                st.info("No results found matching your search criteria.")
        elif search:
             st.info("No trees found in the database to search.")


    # ----------------------------------------------------
    # --- Tab 5: Debug Users ---
    # ----------------------------------------------------
    with tab5:
        st.header("Debug User Status")
        email = st.text_input("Enter user email for debug", key="debug_email_input")
        if st.button("Run Debug Checks", key="run_debug_btn"):
            if email:
                st.subheader(f"Results for: **{email}**")
                info = debug_user_databases(email)
                st.markdown("##### Database Status:")
                for i in info:
                    st.code(i)
            else:
                st.warning("Please enter an email address to debug.")

# ADD THIS BLOCK TO THE END OF YOUR FILE
if __name__ == '__main__':
    # NOTE: This assumes the user is already authenticated and has the 'admin' role
    # In a real app, this would be guarded by authentication logic.
    admin_dashboard()
