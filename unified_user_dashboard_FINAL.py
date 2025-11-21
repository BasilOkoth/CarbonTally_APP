# unified_user_dashboard_with_field_agent.py
import streamlit as st
import pandas as pd
import sqlite3
import time
import random
from pathlib import Path
import plotly.express as px

# ----------------- CONFIGURATION -----------------
BASE_DIR = Path(__file__).parent if "__file__" in locals() else Path.cwd()
DATA_DIR = BASE_DIR / "data"
SQLITE_DB = DATA_DIR / "trees.db"
DATA_DIR.mkdir(exist_ok=True, parents=True)

# ----------------- DATABASE -----------------
def get_db_connection():
    return sqlite3.connect(SQLITE_DB)

# ----------------- FIELD AGENT MANAGEMENT -----------------
def generate_field_password():
    """Generates a random 4-digit password prefixed with 'CT'."""
    number = str(random.randint(1000, 9999))
    return f"CT{number}"

def manage_field_agent_credentials(tree_tracking_number, user_name):
    """Manage field agent password generation and expiration
    Field Agent Login: Username = Tree Tracking Number, Password = Field Agent Password
    """
    st.subheader("🛡 Field Agent Access")
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()

        # Check if password exists and is still valid
        c.execute("SELECT field_password, token_created_at FROM users WHERE treeTrackingNumber = ?", (tree_tracking_number,))
        result = c.fetchone()
        now = int(time.time())

        st.info(f"**Field Agent Login Details:**\n- **Username:** `{tree_tracking_number}` (Your Tree Tracking Number)\n- **Password:** The password generated below.")

        if result:
            password, created_at = result[0], result[1]
            remaining_time_seconds = max(0, 86400 - (now - created_at)) if created_at else 0
            hours = remaining_time_seconds // 3600
            minutes = (remaining_time_seconds % 3600) // 60

            if password and created_at and remaining_time_seconds > 0:
                st.success(f"🔑 **Active Field Password:** `{password}` (Expires in {hours} hrs {minutes} mins)")
                if st.button("🔄 Regenerate Password", key="regenerate_fa_pass"):
                    new_pass = generate_field_password()
                    c.execute("""
                        UPDATE users SET field_password = ?, token_created_at = ?
                        WHERE treeTrackingNumber = ?
                    """, (new_pass, now, tree_tracking_number))
                    conn.commit()
                    st.success(f"✅ New Password Generated: `{new_pass}` (valid 24 hrs)")
                    st.experimental_rerun()
            else:
                if result[0] and result[1] and remaining_time_seconds <= 0:
                    st.warning(f"🔑 Field Password: `{password}` (Expired! Please regenerate.)")
                st.info("No active field password found or valid creation time. Generate one below.")
                if st.button("➕ Generate New Password", key="generate_new_fa_pass"):
                    new_pass = generate_field_password()
                    c.execute("""
                        UPDATE users SET field_password = ?, token_created_at = ?
                        WHERE treeTrackingNumber = ?
                    """, (new_pass, now, tree_tracking_number))
                    conn.commit()
                    st.success(f"✅ Password Created: `{new_pass}` (valid 24 hrs)")
                    st.experimental_rerun()
        else:
            st.info("No field agent record found. Generate a password to create one.")
            if st.button("➕ Generate New Password", key="generate_new_fa_pass_new"):
                new_pass = generate_field_password()
                c.execute("""
                    INSERT INTO users (full_name, email, treeTrackingNumber, field_password, token_created_at, role, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (user_name, f"field_agent_{tree_tracking_number}@carbontally.com", tree_tracking_number, new_pass, now, "field_agent", "approved"))
                conn.commit()
                st.success(f"✅ Password Created: `{new_pass}` (valid 24 hrs)")
                st.experimental_rerun()
    except Exception as e:
        st.error(f"Error managing field agent credentials: {e}")
    finally:
        if conn:
            conn.close()

# ----------------- LOAD TREE DATA -----------------
def load_tree_data(tree_tracking_number):
    try:
        conn = get_db_connection()
        df = pd.read_sql_query(
            "SELECT * FROM trees WHERE treeTrackingNumber = ?", 
            conn, params=(tree_tracking_number,)
        )
        return df
    except Exception as e:
        st.error(f"Error loading tree data: {e}")
        return pd.DataFrame()
    finally:
        if 'conn' in locals():
            conn.close()

# ----------------- METRICS -----------------
def calculate_metrics(trees_df):
    if trees_df.empty:
        return {
            'total_trees':0, 'trees_alive':0, 'co2_absorbed':0.0,
            'health_score':0, 'species_count':{}
        }
    total_trees = len(trees_df)
    trees_alive = len(trees_df[trees_df['status'].str.lower()=='alive'])
    co2_absorbed = trees_df['co2_kg'].sum() if 'co2_kg' in trees_df.columns else 0.0
    species_count = trees_df['local_name'].value_counts().to_dict() if 'local_name' in trees_df.columns else {}
    
    # Simple health score
    health_score = int((trees_alive / total_trees)*100) if total_trees else 0
    return {
        'total_trees':total_trees,
        'trees_alive':trees_alive,
        'co2_absorbed':co2_absorbed,
        'health_score':health_score,
        'species_count':species_count,
    }

# ----------------- DASHBOARD -----------------
def unified_user_dashboard():
    if "user" not in st.session_state or not st.session_state.get("user"):
        st.error("🔒 Please log in")
        return
    
    user_data = st.session_state.user
    tree_tracking_number = user_data.get("treeTrackingNumber")
    username = user_data.get("username", "User")

    st.markdown(f"## 🌳 {username}'s Forest Dashboard")
    
    # Display Tree Tracking Number boldly and clearly
    st.markdown(f"### **Tracking Number:** <span style='color: #28a745; font-size: 1.5em;'>`{tree_tracking_number}`</span>", unsafe_allow_html=True)
    
    trees_df = load_tree_data(tree_tracking_number)
    metrics = calculate_metrics(trees_df)

    # Key metrics (Well designed and modern - using st.metric)
    st.markdown("### 📊 Tree Metrics")
    col1,col2,col3,col4 = st.columns(4)
    with col1:
        st.metric("Total Trees", metrics['total_trees'], delta_color="off")
    with col2:
        st.metric("Trees Alive", metrics['trees_alive'], delta_color="off")
    with col3:
        st.metric("CO₂ Absorbed (kg)", f"{metrics['co2_absorbed']:.2f}", delta_color="off")
    with col4:
        st.metric("Forest Health", f"{metrics['health_score']} %", delta_color="off")

    st.markdown("---")
    
    # Field agent password (Keep this here for easy access, as it's a utility for the user)
    manage_field_agent_credentials(tree_tracking_number, username)

    st.markdown("---")

    # Tree Inventory (Appears first below the metrics)
    st.subheader("📋 Tree Inventory")
    if not trees_df.empty:
        st.dataframe(trees_df)
        st.download_button("Download Trees CSV", trees_df.to_csv(index=False).encode(), "my_trees.csv")
    else:
        st.info("No trees found for your tracking number.")

    st.markdown("---")
    
    # Species Distribution
    if metrics['species_count']:
        st.subheader("🌲 Species Distribution")
        df_species = pd.DataFrame(metrics['species_count'], index=['Count']).T.sort_values('Count',ascending=False)
        fig = px.bar(df_species, x=df_species.index, y='Count', color=df_species.index, 
                     color_discrete_sequence=px.colors.sequential.Greens,
                     title="Tree Count by Species")
        fig.update_layout(xaxis_title="Species Local Name", yaxis_title="Number of Trees")
        st.plotly_chart(fig, use_container_width=True)

    # Growth Stages section removed as requested
    
# ----------------- MAIN -----------------
if __name__=="__main__":
    unified_user_dashboard()
