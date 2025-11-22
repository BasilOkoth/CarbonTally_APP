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
from kobo_integration import generate_qr_code 

# ——— Paths & Configuration ———
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(exist_ok=True, parents=True)
SQLITE_DB = DATA_DIR / 'trees.db'
MONITORING_DB_PATH = DATA_DIR / 'monitoring.db'
ST_THEME_COLOR = "#1D7749"  # Forest Green

# ——— Helper Functions ———
def get_trees_db_connection():
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
        result = pd.read_sql_query("SELECT SUM(co2_kg) FROM tree_monitoring", conn).iloc[0, 0]
        return result if result else 0.0
    except Exception as e:
        logger.warning(f"Error calculating carbon sequestration: {e}")
        return 0.0
    finally:
        conn.close()

def get_survival_rate():
    total_trees = get_total_trees_planted()
    if total_trees == 0: return 0.0
    conn = get_monitoring_db_connection()
    if not conn: return 0.0
    try:
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
    tree_count = get_user_trees_count(user_data.get('tracking_number'))
    if tree_count > 0:
        return False, f"Cannot remove: user has {tree_count} trees."
    success, msg = remove_user_from_sqlite_only(user_data['uid'], user_data.get('tracking_number'))
    try:
        delete_user(user_data['uid'])
    except Exception as e:
        logger.error(f"Error deleting user from Firebase: {e}")
    return success, msg

def force_remove_user(user_data):
    tree_count = get_user_trees_count(user_data.get('tracking_number'))
    remove_user_from_sqlite_only(user_data['uid'], user_data.get('tracking_number'))
    try:
        delete_user(user_data['uid'])
    except Exception as e:
        logger.error(f"Error deleting user from Firebase: {e}")
    return True, f"Force removed user and {tree_count} trees."

# --- Chart Placeholder Functions ---
def generate_planting_trend_data():
    dates = [datetime.now() - timedelta(days=i) for i in range(30)]
    trees = np.random.randint(50, 200, 30)
    df = pd.DataFrame({'Date': dates, 'Trees Planted': trees})
    return df.sort_values('Date')

def generate_species_data():
    species = ['Oak', 'Maple', 'Pine', 'Birch', 'Sequoia', 'Redwood', 'Palm']
    counts = np.random.randint(500, 5000, len(species))
    df = pd.DataFrame({'Species': species, 'Count': counts})
    return df.sort_values('Count', ascending=False)

# --- Admin Dashboard ---
def admin_dashboard():
    if "refresh_dashboard" not in st.session_state:
        st.session_state.refresh_dashboard = False
    if st.session_state.refresh_dashboard:
        st.session_state.refresh_dashboard = False
        return  # Safe refresh

    st.markdown(f"""
        <style>
            .main-header {{color:{ST_THEME_COLOR}; font-weight:700; margin-bottom:20px; padding-left:10px;}}
            .metric-card {{background-color:#f7f9fc; border-left:5px solid {ST_THEME_COLOR}; border-radius:8px;
                padding:15px; box-shadow:0 4px 6px rgba(0,0,0,0.05); margin-bottom:20px;}}
            .metric-label {{font-size:0.9rem; color:#6c757d; font-weight:500;}}
            .metric-value {{font-size:1.8rem; font-weight:700; color:#212529; margin-top:5px;}}
        </style>
    """, unsafe_allow_html=True)
    st.markdown('<h1 class="main-header">🌳 CarbonTally Admin Portal</h1>', unsafe_allow_html=True)

    # Fetch users
    try:
        all_users = get_all_users()
    except Exception as e:
        logger.error(f"Error fetching all users: {e}")
        st.error("Could not load users from Firebase.")
        all_users = []

    # Metrics
    total_trees = get_total_trees_planted()
    total_users = get_total_users()
    total_carbon = get_total_carbon_sequestered()
    survival_rate = get_survival_rate()
    approved_users_count = len([u for u in all_users if u.get('status') == 'approved'])

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Trees", total_trees)
    col2.metric("Registered Agents", total_users, f"{approved_users_count} Approved")
    col3.metric("CO₂ Offset (kg)", f"{total_carbon:.0f}")
    col4.metric("Survival Rate", f"{survival_rate:.1f}%")

    # Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🌳 Tree Inventory",
        "👥 User Management",
        "📊 Analytics & Trends",
        "🔍 Tree Lookup",
        "🐛 Debug Users"
    ])

    # --- Tab 1: Tree Inventory ---
    with tab1:
        st.subheader("Complete Tree Inventory")
        try:
            conn = get_trees_db_connection()
            trees_df = pd.read_sql_query("SELECT * FROM trees", conn)
        except Exception as e:
            logger.error(f"Error fetching trees: {e}")
            trees_df = pd.DataFrame()
        finally:
            conn.close()
        if trees_df.empty:
            st.info("No trees found.")
        else:
            st.dataframe(trees_df)
            st.download_button("⬇️ Download Trees CSV", trees_df.to_csv(index=False).encode(), "trees.csv")

    # --- Tab 2: User Management ---
    with tab2:
        st.subheader("Field Agent Management")
        if st.button("🔄 Sync Users from Firebase"):
            sync_users_from_firestore()
            st.session_state.refresh_dashboard = True
            st.info("Users synced. Refreshing...")
            return

        pending = [u for u in all_users if u.get('status') == 'pending']
        approved = [u for u in all_users if u.get('status') in ['approved', 'rejected']]

        st.markdown("#### Pending Approvals")
        if pending:
            pending_df = pd.DataFrame([{
                'email': u.get('email'),
                'name': u.get('fullName'),
                'tracking_number': u.get('treeTrackingNumber'),
                'uid': u.get('uid')
            } for u in pending])
            st.dataframe(pending_df[['email','name','tracking_number']])
            selected = st.selectbox("Select Agent", pending_df['email'])
            if selected:
                u = pending_df[pending_df['email']==selected].iloc[0].to_dict()
                col1, col2 = st.columns(2)
                with col1:
                    if st.button(f"✅ Approve {u['name']}"):
                        approve_user(u['uid'])
                        send_approval_email(u)
                        st.session_state.refresh_dashboard = True
                        st.info(f"{u['name']} approved.")
                        return
                with col2:
                    if st.button(f"🚫 Reject {u['name']}"):
                        reject_user(u['uid'])
                        send_rejection_email(u)
                        st.session_state.refresh_dashboard = True
                        st.warning(f"{u['name']} rejected.")
                        return
        else:
            st.info("No pending users.")

        st.markdown("#### Approved & Managed Users")
        if approved:
            approved_df = pd.DataFrame([{
                'email': u.get('email'),
                'name': u.get('fullName'),
                'tracking_number': u.get('treeTrackingNumber'),
                'status': u.get('status'),
                'uid': u.get('uid')
            } for u in approved])
            st.dataframe(approved_df[['email','name','tracking_number','status']])
            selected = st.selectbox("Select Agent to Remove", approved_df['email'], key="approved_select")
            if selected:
                u = approved_df[approved_df['email']==selected].iloc[0].to_dict()
                col1, col2 = st.columns(2)
                with col1:
                    if st.button(f"🗑️ Remove {u['name']}"):
                        success,msg = remove_user_completely(u)
                        st.session_state.refresh_dashboard = True
                        st.info(msg)
                        return
                with col2:
                    if st.button(f"🚨 Force Remove {u['name']}"):
                        success,msg = force_remove_user(u)
                        st.session_state.refresh_dashboard = True
                        st.warning(msg)
                        return
        else:
            st.info("No approved users.")

    # --- Tab 3: Analytics ---
    with tab3:
        st.subheader("Planting Trends (Last 30 Days)")
        trend_data = generate_planting_trend_data()
        chart = alt.Chart(trend_data).mark_line(point=True, color=ST_THEME_COLOR).encode(
            x='Date:T', y='Trees Planted:Q', tooltip=['Date','Trees Planted']
        ).interactive()
        st.altair_chart(chart, use_container_width=True)

        st.subheader("Species Distribution")
        species_data = generate_species_data().head(10)
        chart2 = alt.Chart(species_data).mark_bar(color=ST_THEME_COLOR).encode(
            y=alt.Y('Species', sort='-x'), x='Count', tooltip=['Species','Count']
        )
        st.altair_chart(chart2, use_container_width=True)

    # --- Tab 4: Tree Lookup ---
    with tab4:
        st.subheader("Tree Lookup")
        query = st.text_input("Search Tree")
        try:
            conn = get_trees_db_connection()
            df = pd.read_sql_query("SELECT * FROM trees", conn)
        except:
            df = pd.DataFrame()
        finally:
            conn.close()
        if query and not df.empty:
            res = df[df.apply(lambda row: row.astype(str).str.contains(query, case=False).any(), axis=1)]
            st.dataframe(res)

    # --- Tab 5: Debug Users ---
    with tab5:
        st.subheader("Debug Users")
        email = st.text_input("Enter Email for Debug")
        if st.button("Run Debug"):
            if email:
                info = debug_user_databases(email)
                for i in info:
                    st.code(i)
            else:
                st.warning("Enter email first.")

# Run dashboard
if __name__ == '__main__':
    admin_dashboard()
