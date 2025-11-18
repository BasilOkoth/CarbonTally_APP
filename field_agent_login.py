# field_agent_login.py
import streamlit as st
from shared_agent_utils import is_password_valid, get_latest_password_record

def field_agent_login_ui():
    st.title("🔑 Field Agent Login")
    st.info("Log in with your Tree Tracking Number and the field password (CTXXXX). Passwords are valid for 24 hours.")

    tracking_number = st.text_input("Tree Tracking Number", key="fa_login_tracking")
    password = st.text_input("Field Password", type="password", key="fa_login_password")

    if st.button("Login"):
        if not tracking_number or not password:
            st.error("Please provide both tracking number and password.")
            return

        ok, msg, rec = is_password_valid(tracking_number, password)
        if not ok:
            st.error(f"❌ {msg}")
            # If there's a record, show created/expiry to help debug
            if rec:
                st.info(f"Stored password created_at={rec[1]}, expiry={rec[2]}")
            return

        # success
        st.success("✅ Login successful.")
        # store session state for portal
        st.session_state["field_agent_authenticated"] = True
        st.session_state["field_agent_tracking_number"] = tracking_number
        # set a friendly name from the latest record if any (fallback)
        if rec and len(rec) >= 3:
            st.session_state["field_agent_name"] = f"Field Agent {tracking_number}"
        else:
            st.session_state["field_agent_name"] = f"Field Agent {tracking_number}"
        st.experimental_rerun()

    st.markdown("---")
    st.write("Troubleshooting:")
    st.write("- If login fails, ask the owner of the tracking number to generate a new password from their dashboard.")
