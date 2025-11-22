import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import sqlite3
import datetime
import uuid
from pathlib import Path

# This file implements the donor dashboard that can be accessed without login
# It allows donors to view impact, make donations, and track trees they've funded

# Configuration
BASE_DIR = Path(__file__).parent if "__file__" in locals() else Path.cwd()
DATA_DIR = BASE_DIR / "data"
SQLITE_DB = DATA_DIR / "trees.db"

# New function to initialize the donor database tables
def initialize_donor_database():
    """Initializes the donations and donated_trees tables."""
    conn = sqlite3.connect(SQLITE_DB)
    try:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS donations (
                donation_id TEXT PRIMARY KEY,
                donor_name TEXT,
                donor_email TEXT,
                institution_id TEXT, 
                num_trees INTEGER,   
                amount REAL,
                currency TEXT,
                donation_date TEXT,
                payment_status TEXT, 
                message TEXT,        
                transaction_id TEXT UNIQUE
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS donated_trees (
                donated_tree_id TEXT PRIMARY KEY,
                donation_id TEXT,
                tree_id TEXT,
                tree_count INTEGER,
                FOREIGN KEY (donation_id) REFERENCES donations(donation_id)
            )
        ''')
        conn.commit()
        # st.success("Donor database initialized successfully (donations, donated_trees tables).") # Can be noisy, uncomment for debug
    except Exception as e:
        st.error(f"Error initializing donor database: {e}")
    finally:
        conn.close()

def donor_dashboard():
    """
    Main donor dashboard that can be accessed without login
    """
    st.markdown("<h1 class='header-text'>🌱 Donor Dashboard</h1>", unsafe_allow_html=True)
    
    # Introduction section
    st.markdown("""
    <div style="background-color: #f0f7f0; border-radius: 8px; padding: 1.2rem; margin-bottom: 1.5rem;">
        <h3 style="margin-top:0; color: #1D7749;">Support Tree Planting Initiatives</h3>
        <p>Your donation directly supports tree planting efforts by our partner institutions and individuals. 
        Each tree planted helps combat climate change, restore ecosystems, and create a greener future.</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Main donor dashboard tabs
    tab1, tab2, tab3 = st.tabs(["🌍 Make a Donation", "📊 Track Your Impact", "ℹ️ About Our Program"])
    
    with tab1:
        donation_section()
    
    with tab2:
        impact_tracking_section()
    
    with tab3:
        about_program_section()

def donation_section():
    """
    Section for making new donations
    """
    st.markdown("<h3 style='color: #1D7749; margin-top:1rem; margin-bottom: 0.5rem;'>Make a Donation</h3>", unsafe_allow_html=True)
    
    # Get qualifying institutions
    institutions = get_qualifying_institutions()
    
    if not institutions:
        st.warning("No qualifying institutions found at the moment. Please check back later.")
        return
    
    # Donation form
    with st.form("donation_form"):
        # Institution selection
        selected_institution = st.selectbox(
            "Select an institution to support",
            options=institutions,
            format_func=lambda x: x
        )
        
        # Number of trees
        num_trees = st.number_input(
            "Number of trees to donate",
            min_value=1,
            max_value=1000,
            value=5,
            step=1
        )
        
        # Calculate amount (assuming $5 per tree)
        amount_per_tree = 5
        total_amount = num_trees * amount_per_tree
        
        st.markdown(f"""
        <div style="background-color: #f0f7f0; border-radius: 8px; padding: 1rem; margin: 1rem 0;">
            <h4 style="margin-top:0; color: #1D7749;">Donation Summary</h4>
            <p><strong>{num_trees} trees</strong> at <strong>${amount_per_tree} per tree</strong></p>
            <p style="font-size: 1.2rem; font-weight: bold;">Total: ${total_amount}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Donor information
        st.markdown("<h4 style='color: #333;'>Your Information</h4>", unsafe_allow_html=True)
        donor_name = st.text_input("Your Name")
        donor_email = st.text_input("Email Address")
        
        # Optional message
        message = st.text_area("Optional Message", max_chars=200)
        
        # Submit button
        submitted = st.form_submit_button("Proceed to Payment", use_container_width=True)
        
        if submitted:
            if not donor_name or not donor_email:
                st.error("Please provide your name and email address.")
                return
            
            # Generate donation ID
            donation_id = f"DON-{uuid.uuid4().hex[:8].upper()}"
            
            # Store donation in session state for payment processing
            st.session_state.pending_donation = {
                "donation_id": donation_id,
                "donor_name": donor_name,
                "donor_email": donor_email,
                "institution": selected_institution,
                "num_trees": num_trees,
                "amount": total_amount,
                "currency": "USD",
                "message": message,
                "donation_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "payment_status": "pending"
            }
            
            st.session_state.show_payment = True
            st.rerun()
    
    # Payment processing section (shown after form submission)
    if st.session_state.get("show_payment"):
        donation = st.session_state.pending_donation
        
        st.markdown("<h3 style='color: #1D7749; margin-top:1rem; margin-bottom: 0.5rem;'>Payment</h3>", unsafe_allow_html=True)
        
        st.markdown(f"""
        <div style="background-color: #f0f7f0; border-radius: 8px; padding: 1rem; margin-bottom: 1rem;">
            <h4 style="margin-top:0; color: #1D7749;'>Donation Details</h4>
            <p><strong>Donation ID:</strong> {donation['donation_id']}</p>
            <p><strong>Institution:</strong> {donation['institution']}</p>
            <p><strong>Trees:</strong> {donation['num_trees']}</p>
            <p><strong>Amount:</strong> ${donation['amount']}</p>
        </div>
        """, unsafe_allow_html=True)
        
        payment_col1, payment_col2 = st.columns(2)
        
        with payment_col1:
            if st.button("Pay with PayPal", use_container_width=True):
                process_successful_donation(donation)
                st.success("Payment successful! Thank you for your donation.")
                st.session_state.show_payment = False
                st.session_state.show_certificate = True
                st.rerun()
        
        with payment_col2:
            if st.button("Pay with Credit Card", use_container_width=True):
                process_successful_donation(donation)
                st.success("Payment successful! Thank you for your donation.")
                st.session_state.show_payment = False
                st.session_state.show_certificate = True
                st.rerun()
    
    # Certificate section (shown after successful payment)
    if st.session_state.get("show_certificate"):
        donation = st.session_state.pending_donation
        
        st.markdown("<h3 style='color: #1D7749; margin-top:1rem; margin-bottom: 0.5rem;'>Thank You!</h3>", unsafe_allow_html=True)
        
        st.markdown(f"""
        <div style="background-color: #f0f7f0; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; text-align: center;">
            <h2 style="margin-top:0; color: #1D7749;">Certificate of Donation</h2>
            <p style="font-size: 1.2rem;">This certifies that</p>
            <p style="font-size: 1.5rem; font-weight: bold;">{donation['donor_name']}</p>
            <p style="font-size: 1.2rem;">has donated</p>
            <p style="font-size: 1.5rem; font-weight: bold;">{donation['num_trees']} Trees</p>
            <p style="font-size: 1.2rem;">to</p>
            <p style="font-size: 1.5rem; font-weight: bold;">{donation['institution']}</p>
            <p style="font-size: 1rem; margin-top: 1.5rem;">Donation ID: {donation['donation_id']}</p>
            <p style="font-size: 1rem;">Date: {donation['donation_date']}</p>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("""
        <p style="text-align: center;">A confirmation email has been sent to your email address.</p>
        <p style="text-align: center;">You can track the impact of your donation using your email address or donation ID.</p>
        """, unsafe_allow_html=True)
        
        if st.button("Make Another Donation", use_container_width=True):
            st.session_state.show_certificate = False
            if "pending_donation" in st.session_state:
                del st.session_state.pending_donation
            st.rerun()

def impact_tracking_section():
    """
    Section for tracking donation impact
    """
    st.markdown("<h3 style='color: #1D7749; margin-top:1rem; margin-bottom: 0.5rem;'>Track Your Impact</h3>", unsafe_allow_html=True)
    
    tracking_col1, tracking_col2 = st.columns(2)
    
    with tracking_col1:
        st.markdown("<h4 style='color: #333;'>Track by Email</h4>", unsafe_allow_html=True)
        email_to_track = st.text_input("Enter your email address", key="track_email")
        track_by_email = st.button("Track Donations", use_container_width=True)
        
        if track_by_email and email_to_track:
            show_donations_by_email(email_to_track)
    
    with tracking_col2:
        st.markdown("<h4 style='color: #333;'>Track by Donation ID</h4>", unsafe_allow_html=True)
        donation_id_to_track = st.text_input("Enter your donation ID", key="track_id")
        track_by_id = st.button("Track Donation", use_container_width=True)
        
        if track_by_id and donation_id_to_track:
            show_donation_by_id(donation_id_to_track)

def about_program_section():
    """
    Section with information about the tree planting program
    """
    st.markdown("<h3 style='color: #1D7749; margin-top:1rem; margin-bottom: 0.5rem;'>About Our Tree Planting Program</h3>", unsafe_allow_html=True)
    
    st.markdown("""
    <div style="background-color: #f0f7f0; border-radius: 8px; padding: 1.2rem; margin-bottom: 1.5rem;">
        <h4 style="margin-top:0; color: #1D7749;'>How It Works</h4>
        <p>1. <strong>You Donate:</strong> Choose an institution and the number of trees you want to fund.</p>
        <p>2. <strong>Trees are Planted:</strong> Our partner institutions and individuals plant the trees using your donation.</p>
        <p>3. <strong>Growth is Monitored:</strong> Trees are regularly monitored for growth and health.</p>
        <p>4. <strong>Impact is Measured:</strong> We calculate the environmental impact of your trees, including CO₂ sequestration.</p>
        <p>5. <strong>You Track Progress:</strong> Use your email or donation ID to track the growth and impact of your trees.</p>
    </div>
    
    <div style="background-color: #f0f7f0; border-radius: 8px; padding: 1.2rem; margin-bottom: 1.5rem;">
        <h4 style="margin-top:0; color: #1D7749;'>Environmental Impact</h4>
        <p>Each tree planted through our program:</p>
        <ul>
            <li>Sequesters approximately 25kg of CO₂ per year when mature</li>
            <li>Provides habitat for local wildlife</li>
            <li>Helps prevent soil erosion</li>
            <li>Improves air quality</li>
            <li>Contributes to biodiversity</li>
        </ul>
    </div>
    
    <div style="background-color: #f0f7f0; border-radius: 8px; padding: 1.2rem; margin-bottom: 1.5rem;">
        <h4 style="margin-top:0; color: #1D7749;'>Our Partners</h4>
        <p>We work with various institutions including schools, community organizations, and environmental groups to plant trees in areas where they're most needed.</p>
        <p>All our partners are vetted to ensure they follow best practices for tree planting and maintenance.</p>
    </div>
    """, unsafe_allow_html=True)

def get_qualifying_institutions():
    """
    Get list of qualifying institutions for donations
    In a real app, this would filter based on criteria
    """
    conn = sqlite3.connect(SQLITE_DB)
    try:
        # In a real app, this would query a table of qualifying institutions
        # For now, we'll get unique institution names from the trees table
        query = "SELECT DISTINCT institution FROM trees WHERE institution IS NOT NULL AND institution != ''"
        df = pd.read_sql(query, conn)
        institutions = df["institution"].tolist()
    except Exception as e:
        st.error(f"Error loading institutions: {str(e)}")
        institutions = []
    finally:
        conn.close()
    
    return institutions

def process_successful_donation(donation):
    """
    Process a successful donation by storing it in the database
    and allocating trees to the donor
    """
    conn = sqlite3.connect(SQLITE_DB)
    try:
        # Insert donation record
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO donations 
            (donation_id, donor_email, donor_name, institution_id, num_trees, amount, currency, donation_date, payment_status, message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            donation["donation_id"],
            donation["donor_email"],
            donation["donor_name"],
            donation["institution"],
            donation["num_trees"],
            donation["amount"],
            donation["currency"],
            donation["donation_date"],
            "approved",
            donation["message"]
        ))
        
        conn.commit()
    except Exception as e:
        st.error(f"Error processing donation: {str(e)}")
        conn.rollback()
    finally:
        conn.close()

def show_donations_by_email(email):
    """
    Show all donations made by a specific email address
    """
    conn = sqlite3.connect(SQLITE_DB)
    try:
        query = "SELECT * FROM donations WHERE donor_email = ? ORDER BY donation_date DESC"
        df = pd.read_sql(query, conn, params=(email,))
        
        if df.empty:
            st.warning(f"No donations found for email: {email}")
            return
        
        st.success(f"Found {len(df)} donation(s) for {email}")
        
        for _, donation in df.iterrows():
            with st.expander(f"Donation {donation['donation_id']} - {donation['donation_date']}"):
                st.markdown(f"""
                **Institution:** {donation['institution_id']}<br>
                **Trees:** {donation['num_trees']}<br>
                **Amount:** ${donation['amount']} {donation['currency']}<br>
                **Status:** {donation['payment_status']}<br>
                **Date:** {donation['donation_date']}
                """, unsafe_allow_html=True)
                
                if donation['message']:
                    st.markdown(f"**Message:** {donation['message']}")
                
                st.info("Tree details will be available once trees are planted.")
    except Exception as e:
        st.error(f"Error retrieving donations: {str(e)}")
    finally:
        conn.close()

def show_donation_by_id(donation_id):
    """
    Show details for a specific donation ID
    """
    conn = sqlite3.connect(SQLITE_DB)
    try:
        query = "SELECT * FROM donations WHERE donation_id = ?"
        df = pd.read_sql(query, conn, params=(donation_id,))
        
        if df.empty:
            st.warning(f"No donation found with ID: {donation_id}")
            return
        
        donation = df.iloc[0]
        
        st.success(f"Found donation {donation_id}")
        
        st.markdown(f"""
        <div style="background-color: #f0f7f0; border-radius: 8px; padding: 1.2rem; margin-bottom: 1.5rem;">
            <h4 style="margin-top:0; color: #1D7749;'>Donation Details</h4>
            <p><strong>Donation ID:</strong> {donation['donation_id']}</p>
            <p><strong>Donor:</strong> {donation['donor_name']}</p>
            <p><strong>Email:</strong> {donation['donor_email']}</p>
            <p><strong>Institution:</strong> {donation['institution_id']}</p>
            <p><strong>Trees:</strong> {donation['num_trees']}</p>
            <p><strong>Amount:</strong> ${donation['amount']} {donation['currency']}</p>
            <p><strong>Status:</strong> {donation['payment_status']}</p>
            <p><strong>Date:</strong> {donation['donation_date']}</p>
        </div>
        """, unsafe_allow_html=True)
        
        if donation['message']:
            st.markdown(f"**Message:** {donation['message']}")
        
        st.info("Tree details will be available once trees are planted.")
    except Exception as e:
        st.error(f"Error retrieving donation: {str(e)}")
    finally:
        conn.close()

# Initialize session state variables
def init_session_state():
    """
    Initialize session state variables for the donor dashboard
    """
    if "show_payment" not in st.session_state:
        st.session_state.show_payment = False
    
    if "show_certificate" not in st.session_state:
        st.session_state.show_certificate = False

# Main function to be called from app.py
def guest_donor_dashboard_ui():
    """
    Main entry point for the donor dashboard
    """
    init_session_state()
    donor_dashboard()
