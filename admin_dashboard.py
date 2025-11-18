# admin_dashboard.py - FULLY CORRECTED

import streamlit as st
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime
from firebase_auth_integration import (
    get_all_users,
    sync_users_from_firestore,
    approve_user, reject_user, delete_user,
    send_approval_email, send_rejection_email
)
from kobo_integration import generate_qr_code

# ——— Paths ———
BASE_DIR = Path(__file__).parent
SQLITE_DB = BASE_DIR / 'data' / 'trees.db'
MONITORING_DB_PATH = BASE_DIR / 'data' / 'monitoring.db'

# ——— Helper Functions ———
def get_trees_db_connection():
    return sqlite3.connect(str(SQLITE_DB))

def get_monitoring_db_connection():
    try:
        return sqlite3.connect(str(MONITORING_DB_PATH))
    except sqlite3.Error as e:
        st.error(f"Monitoring DB error: {e}")
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
    except:
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
    except:
        return 0.0
    finally:
        conn.close()

def get_user_trees_count(tracking_number):
    if not tracking_number: return 0
    conn = get_trees_db_connection()
    try:
        return pd.read_sql_query(
            "SELECT COUNT(*) FROM trees WHERE treeTrackingNumber = ?", conn, params=(tracking_number,)
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
        if user: debug_info.append(f"✅ Found in SQLite users: {user}")
        else: debug_info.append("❌ Not in SQLite users")
        cur.execute("SELECT uid, email FROM pending_users WHERE email=?", (user_email,))
        pending = cur.fetchone()
        if pending: debug_info.append(f"✅ Found in pending_users: {pending}")
        else: debug_info.append("❌ Not in pending_users")
        if user and len(user) > 2:
            debug_info.append(f"🌳 User has {get_user_trees_count(user[2])} trees")
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
        delete_user(user_data['uid'])
    except:
        pass
    return success, msg

def force_remove_user(user_data):
    tree_count = get_user_trees_count(user_data.get('treeTrackingNumber'))
    remove_user_from_sqlite_only(user_data['uid'], user_data.get('treeTrackingNumber'))
    try:
        delete_user(user_data['uid'])
    except:
        pass
    return True, f"Force removed user and {tree_count} trees."

# ——— Dashboard ———
def admin_dashboard():
    st.title("🌳 Admin Dashboard")

    if st.button("🔄 Sync Users from Firebase"):
        sync_users_from_firestore()
        st.success("Users synced")

    # System Metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Trees", get_total_trees_planted())
    col2.metric("Total Users", get_total_users())
    col3.metric("CO₂ Sequestered (kg)", f"{get_total_carbon_sequestered():,.2f}")
    col4.metric("Survival Rate (%)", f"{get_survival_rate():.2f}")

    # Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🌳 Tree Management",
        "👥 User Management",
        "📊 Analytics",
        "🔍 Tree Lookup",
        "🐛 Debug Users"
    ])

    # --- Tab 1: Tree Management ---
    with tab1:
        st.subheader("Tree Inventory")
        try:
            conn = get_trees_db_connection()
            trees_df = pd.read_sql_query("SELECT * FROM trees", conn)
        except:
            trees_df = pd.DataFrame()
        finally:
            conn.close()
        if trees_df.empty:
            st.info("No trees found.")
        else:
            st.dataframe(trees_df)
            st.download_button("Download CSV", trees_df.to_csv(index=False).encode(), "trees.csv")

    # --- Tab 2: User Management ---
    with tab2:
        st.subheader("Users")
        users = get_all_users()
        pending = [u for u in users if u['status']=='pending']
        approved = [u for u in users if u['status']=='approved']

        st.markdown("#### Pending Users")
        for u in pending:
            st.write(u['email'])
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Approve", key=f"app_{u['uid']}"):
                    approve_user(u['uid'])
                    send_approval_email(u)
                    st.success(f"{u['email']} approved")
            with col2:
                if st.button("Reject", key=f"rej_{u['uid']}"):
                    reject_user(u['uid'])
                    send_rejection_email(u)
                    st.warning(f"{u['email']} rejected")

        st.markdown("#### Approved Users")
        for u in approved:
            st.write(u['email'])
            tree_count = get_user_trees_count(u.get('treeTrackingNumber'))
            st.write(f"🌳 Trees: {tree_count}")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Remove", key=f"rem_{u['uid']}"):
                    if tree_count == 0:
                        remove_user_completely(u)
                        st.success("User removed")
                    else:
                        st.warning("User has trees; cannot remove")
            with col2:
                if st.button("Force Remove", key=f"force_{u['uid']}"):
                    force_remove_user(u)
                    st.success("Force removed")

    # --- Tab 3: Analytics ---
    with tab3:
        st.subheader("Analytics")
        st.info("Graphs and charts can go here")

    # --- Tab 4: Tree Lookup ---
    with tab4:
        st.subheader("Search Trees")
        search = st.text_input("Search by Tree ID or Name")
        if search and not trees_df.empty:
            results = trees_df[
                trees_df['tree_id'].astype(str).str.contains(search, case=False, na=False)
            ]
            st.dataframe(results)
            if not results.empty:
                selected_tree = st.selectbox("Select Tree", results['tree_id'].astype(str))
                tree_data = results[results['tree_id']==int(selected_tree)].iloc[0].to_dict()
                st.json(tree_data)
                qr_path = generate_qr_code(tree_id=tree_data['tree_id'], treeTrackingNumber=tree_data.get('treeTrackingNumber'))
                st.image(qr_path)

    # --- Tab 5: Debug Users ---
    with tab5:
        st.subheader("Debug User")
        email = st.text_input("Enter user email for debug")
        if email:
            info = debug_user_databases(email)
            for i in info:
                st.write(i)
