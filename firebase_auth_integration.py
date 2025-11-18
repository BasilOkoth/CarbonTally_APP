import time
import streamlit as st
import firebase_admin
from firebase_admin import credentials, auth, firestore
from firebase_admin import exceptions
from firebase_admin.exceptions import FirebaseError
import uuid
from datetime import datetime
import re
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
import logging
import sqlite3
import pandas as pd
import requests  # Add this import for REST API calls

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Configuration
BASE_DIR = Path(__file__).parent if "__file__" in locals() else Path.cwd()
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True, parents=True)
BASE_DIR = Path(__file__).parent
SQLITE_DB = BASE_DIR / 'data' / 'trees.db'

def get_db_connection():
    return sqlite3.connect(str(SQLITE_DB))

def init_sql_tables():
    conn = None
    try:
        SQLITE_DB.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(SQLITE_DB))
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT UNIQUE,
                fullName TEXT,
                email TEXT UNIQUE,
                institution TEXT,
                role TEXT DEFAULT 'individual',
                status TEXT DEFAULT 'pending',
                treeTrackingNumber TEXT UNIQUE,
                createdAt TEXT DEFAULT CURRENT_TIMESTAMP,
                approvedAt TEXT,
                field_password TEXT,
                token_created_at INTEGER,
                firebase_doc_id TEXT,
                last_sync_time TEXT,
                approved INTEGER DEFAULT 0
            );
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS pending_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fullName TEXT,
                email TEXT UNIQUE,
                uid TEXT UNIQUE,
                role TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS institutions (
                id TEXT PRIMARY KEY,
                fullName TEXT,
                join_date TEXT
            );
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS trees (
                tree_id TEXT PRIMARY KEY,
                scientific_name TEXT,
                local_name TEXT,
                latitude REAL,
                longitude REAL,
                planters_name TEXT,
                treeTrackingNumber TEXT UNIQUE,
                dbh_cm REAL,
                height_m REAL,
                co2_kg REAL,
                rcd_cm REAL,
                institution TEXT,
                date_planted TEXT,
                status TEXT,
                last_monitored_at TEXT
            );
        """)

        conn.commit()
        print("✅ SQLite tables initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing SQL tables: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# Initialize tables on import
init_sql_tables()

# Email Templates
EMAIL_TEMPLATES = {
    "approval": {
        "subject": "CarbonTally - Your Account Has Been Approved",
        "body": """
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 5px;">
                <div style="text-align: center; margin-bottom: 20px;">
                    <h2 style="color: #2e8b57;">CarbonTally</h2>
                </div>
                <p>Dear {fullName},</p>
                <p>Congratulations! Your CarbonTally account has been approved.</p>
                <p>You can now log in using your email and password at <a href="{app_url}" style="color: #2e8b57;">CarbonTally</a>.</p>
                <p><strong>Your Tree Tracking Number:</strong> {treeTrackingNumber}</p>
                <p>This unique tracking number will help you monitor and track all trees you plant through our platform.</p>
                <p>Thank you for joining our mission to combat climate change through tree planting initiatives!</p>
                <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e0e0e0; text-align: center; font-size: 0.8em; color: #666;">
                    <p>CarbonTally - Empowering Tree Monitoring and Climate Action</p>
                    <p>If you have any questions, please contact us at <a href="mailto:okothbasil45@gmail.com" style="color: #2e8b57;">okothbasil45@gmail.com</a></p>
                </div>
            </div>
        </body>
        </html>
        """
    },
    "rejection": {
        "subject": "CarbonTally - Account Application Status",
        "body": """
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 5px;">
                <div style="text-align: center; margin-bottom: 20px;">
                    <h2 style="color: #2e8b57;">CarbonTally</h2>
                </div>
                <p>Dear {fullName},</p>
                <p>Thank you for your interest in CarbonTally.</p>
                <p>We regret to inform you that your account application has not been approved at this time.</p>
                <p>This could be due to various reasons, such as incomplete information or not meeting our current criteria.</p>
                <p>You are welcome to submit a new application with complete information or contact us for more details.</p>
                <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e0e0e0; text-align: center; font-size: 0.8em; color: #666;">
                    <p>CarbonTally - Empowering Tree Monitoring and Climate Action</p>
                    <p>If you have any questions, please contact us at <a href="mailto:okothbasil45@gmail.com" style="color: #2e8b57;">okothbasil45@gmail.com</a></p>
                </div>
            </div>
        </body>
        </html>
        """
    },
    "password_reset": {
        "subject": "CarbonTally - Password Reset Link",
        "body": """
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 5px;">
                <div style="text-align: center; margin-bottom: 20px;">
                    <h2 style="color: #2e8b57;">CarbonTally</h2>
                </div>
                <p>Dear User,</p>
                <p>We received a request to reset your password for your CarbonTally account.</p>
                <p>To reset your password, please click on the link below:</p>
                <p style="text-align: center;">
                    <a href="{reset_link}" style="display: inline-block; padding: 10px 20px; background-color: #2e8b57; color: white; text-decoration: none; border-radius: 5px;">Reset Password</a>
                </p>
                <p>This link will expire in 24 hours.</p>
                <p>If you did not request a password reset, please ignore this email or contact us if you have concerns.</p>
                <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e0e0e0; text-align: center; font-size: 0.8em; color: #666;">
                    <p>CarbonTally - Empowering Tree Monitoring and Climate Action</p>
                    <p>If you have any questions, please contact us at <a href="mailto:okothbasil45@gmail.com" style="color: #2e8b57;">okothbasil45@gmail.com</a></p>
                </div>
            </div>
        </body>
        </html>
        """
    }
}

def initialize_firebase():
    """Initialize Firebase Admin SDK from Streamlit secrets"""
    if firebase_admin._apps:
        if 'firebase_db' not in st.session_state:
            st.session_state.firebase_db = firestore.client()
        return st.session_state.firebase_db

    try:
        config = st.secrets["FIREBASE_CONFIG"]
        firebase_config = {
            "type": config["type"],
            "project_id": config["project_id"],
            "private_key_id": config["private_key_id"],
            "private_key": config["private_key"].replace("\\n", "\n"),
            "client_email": config["client_email"],
            "client_id": config["client_id"],
            "auth_uri": config["auth_uri"],
            "token_uri": config["token_uri"],
            "auth_provider_x509_cert_url": config["auth_provider_x509_cert_url"],
            "client_x509_cert_url": config["client_x509_cert_url"]
        }

        cred = credentials.Certificate(firebase_config)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        st.session_state.firebase_db = db
        return db
    except Exception as e:
        st.error(f"Firebase initialization failed: {e}")
        show_firebase_setup_guide()
        return None

def firebase_login_ui():
    """Display Firebase login UI and handle authentication with REAL Firebase Auth"""
    st.markdown("<h3 style='text-align: center; color: #1D7749;'>Login to Your Account</h3>", unsafe_allow_html=True)
    
    with st.form("firebase_login_form"):
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        submitted = st.form_submit_button("Login", use_container_width=True)
        
        if submitted:
            if not email or not password:
                st.warning("Please enter both email and password")
            else:
                try:
                    # Use Firebase REST API for actual authentication
                    # Get Firebase API key from secrets - try multiple locations
                    api_key = None
                    
                    # Try getting from FIREBASE_CONFIG first
                    if 'FIREBASE_CONFIG' in st.secrets and 'api_key' in st.secrets['FIREBASE_CONFIG']:
                        api_key = st.secrets['FIREBASE_CONFIG']['api_key']
                    # Try getting from root level
                    elif 'FIREBASE_WEB_API_KEY' in st.secrets:
                        api_key = st.secrets['FIREBASE_WEB_API_KEY']
                    
                    if not api_key:
                        st.error("❌ Firebase API key not configured. Please check your secrets.toml file.")
                        return
                    
                    # Firebase Auth REST API endpoint
                    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
                    
                    # Prepare the authentication request
                    payload = {
                        "email": email,
                        "password": password,
                        "returnSecureToken": True
                    }
                    
                    # Make the authentication request
                    response = requests.post(url, json=payload)
                    result = response.json()
                    
                    if response.status_code == 200:
                        # Authentication successful
                        user_id = result.get('localId')
                        
                        # Get user data from Firestore
                        db = initialize_firebase()
                        if not db:
                            st.error("Failed to connect to Firestore")
                            return
                            
                        user_doc = db.collection('users').document(user_id).get()
                        
                        if user_doc.exists:
                            user_data = user_doc.to_dict()
                            
                            # Check if account is approved
                            if user_data.get('status') != 'approved':
                                st.error("❌ Your account is pending approval. Please wait for admin approval.")
                                return
                            
                            # Set session state with user data
                            st.session_state.user = {
                                'uid': user_id,
                                'email': email,
                                'username': user_data.get('username', email.split('@')[0]),
                                'displayName': user_data.get('fullName', 'User'),
                                'role': user_data.get('role', 'individual'),
                                'user_type': user_data.get('role', 'individual'),
                                'institution': user_data.get('institution', ''),
                                'treeTrackingNumber': user_data.get('treeTrackingNumber', '')
                            }
                            
                            st.session_state.authenticated = True
                            st.session_state.firebase_user = True
                            
                            # Redirect based on role
                            if user_data.get('role') == 'admin':
                                st.session_state.page = "Admin Dashboard"
                            else:
                                st.session_state.page = "User Dashboard"
                            
                            st.success(f"✅ Welcome {user_data.get('fullName', 'User')}!")
                            st.rerun()
                        else:
                            st.error("❌ User profile not found in Firestore. Please contact support.")
                    else:
                        # Authentication failed - handle specific errors
                        error_message = result.get('error', {}).get('message', 'Authentication failed')
                        if 'EMAIL_NOT_FOUND' in error_message:
                            st.error("❌ No account found with this email address.")
                        elif 'INVALID_PASSWORD' in error_message:
                            st.error("❌ Incorrect password. Please try again.")
                        elif 'INVALID_LOGIN_CREDENTIALS' in error_message:
                            st.error("❌ Invalid email or password.")
                        elif 'USER_DISABLED' in error_message:
                            st.error("❌ This account has been disabled. Please contact support.")
                        elif 'TOO_MANY_ATTEMPTS_TRY_LATER' in error_message:
                            st.error("❌ Too many failed login attempts. Please try again later.")
                        else:
                            st.error(f"❌ Authentication failed: {error_message}")
                            
                except Exception as e:
                    st.error(f"❌ An unexpected error occurred: {str(e)}")
def firebase_signup_ui():
    """Display Firebase signup UI and handle new user registration"""
    st.markdown("<h3 style='text-align: center; color: #1D7749;'>Create New Account</h3>", unsafe_allow_html=True)

    with st.form("firebase_signup_form"):
        email = st.text_input("Email", key="signup_email")
        password = st.text_input("Password", type="password", key="signup_password", 
                               help="Password must be at least 6 characters long")
        confirm_password = st.text_input("Confirm Password", type="password", key="signup_confirm_password")
        full_name = st.text_input("Full Name", key="signup_full_name")
        user_type = st.selectbox("Account Type", options=["individual", "institution"], key="signup_user_type")
        institution_name = ""
        if user_type == "institution":
            institution_name = st.text_input("Institution Name", key="signup_institution_name")

        submitted = st.form_submit_button("Register", use_container_width=True)

        if submitted:
            if not email or not password or not confirm_password or not full_name:
                st.warning("Please fill in all required fields.")
            elif password != confirm_password:
                st.error("Passwords do not match.")
            elif len(password) < 6:
                st.error("Password must be at least 6 characters long.")
            elif user_type == "institution" and not institution_name:
                st.warning("Please enter institution name for institution account type.")
            else:
                try:
                    # Use REST API for user creation to ensure proper authentication
                    # Get Firebase API key from secrets
                    api_key = None
                    if 'FIREBASE_CONFIG' in st.secrets and 'api_key' in st.secrets['FIREBASE_CONFIG']:
                        api_key = st.secrets['FIREBASE_CONFIG']['api_key']
                    elif 'FIREBASE_WEB_API_KEY' in st.secrets:
                        api_key = st.secrets['FIREBASE_WEB_API_KEY']
                    
                    if not api_key:
                        st.error("Firebase API key not configured.")
                        return
                    
                    # Create user with REST API
                    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={api_key}"
                    payload = {
                        "email": email,
                        "password": password,
                        "returnSecureToken": True
                    }
                    
                    response = requests.post(url, json=payload)
                    result = response.json()
                    
                    if response.status_code == 200:
                        user_id = result.get('localId')
                        tree_tracking_number = f"CT-{uuid.uuid4().hex[:8].upper()}"

                        db = initialize_firebase()
                        user_ref = db.collection('users').document(user_id)
                        user_data = {
                            'email': email,
                            'fullName': full_name,
                            'role': user_type,
                            'status': 'pending',
                            'createdAt': firestore.SERVER_TIMESTAMP,
                            'treeTrackingNumber': tree_tracking_number
                        }
                        if user_type == "institution":
                            user_data['institution'] = institution_name
                        
                        user_ref.set(user_data)
                        add_to_pending_users(user_id, user_data)

                        st.success("✅ Account created successfully! Your account is pending admin approval. You will receive an email once approved.")
                        logger.info(f"New user registered: {email} (UID: {user_id})")
                        time.sleep(3)
                        st.session_state.page = "Login"
                        st.rerun()
                    else:
                        error_message = result.get('error', {}).get('message', 'Registration failed')
                        if 'EMAIL_EXISTS' in error_message:
                            st.error("This email is already registered.")
                        else:
                            st.error(f"Registration failed: {error_message}")
                            
                except Exception as e:
                    st.error(f"An unexpected error occurred: {e}")
def firebase_password_recovery_ui():
    """Password recovery with custom email like approval message"""
    st.markdown("<h3 style='text-align: center; color: #1D7749;'>Password Recovery</h3>", unsafe_allow_html=True)

    with st.form("firebase_password_recovery_form"):
        email = st.text_input("Enter your registered email", key="recovery_email")
        submitted = st.form_submit_button("Send Reset Link", use_container_width=True)

        if submitted:
            if not email:
                st.warning("Please enter your email address.")
            elif not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                st.warning("Please enter a valid email address.")
            else:
                with st.spinner("Sending password reset email..."):
                    try:
                        reset_link = generate_password_reset_link(email)
                        if reset_link:
                            template = EMAIL_TEMPLATES["password_reset"]
                            subject = template["subject"]
                            html_body = template["body"].format(reset_link=reset_link)
                            sent = send_email(email, subject, html_body)
                            if sent:
                                st.success("✅ Password reset link sent! Please check your inbox (and spam folder).")
                            else:
                                st.error("Failed to send email. Please try again later.")
                        else:
                            st.error("No user found with that email or failed to generate reset link.")
                    except Exception as e:
                        st.error(f"An error occurred: {str(e)}")

def firebase_logout():
    """Handle Firebase user logout completely"""
    # Clear all session state related to authentication
    keys_to_clear = ['authenticated', 'user', 'firebase_user']
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    
    # Reset page to landing
    st.session_state.page = "Landing"
    
    st.success("✅ Logged out successfully!")
    st.rerun()

# Keep the rest of your existing functions (they remain the same):
def add_to_pending_users(uid, user_data):
    """Add new user application to pending_users table"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO pending_users (fullName, email, uid, role)
            VALUES (?, ?, ?, ?)
        """, (
            user_data.get('fullName', ''),
            user_data.get('email', ''),
            uid,
            user_data.get('role', 'individual')
        ))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error adding to pending users: {e}")
        return False
    finally:
        conn.close()

def sync_user_to_sql(uid, user_data):
    """Sync approved user data from Firestore to SQL database"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        created_at = user_data.get('createdAt')
        if isinstance(created_at, datetime):
            created_at = created_at.strftime('%Y-%m-%d %H:%M:%S')
        
        c.execute("SELECT 1 FROM users WHERE uid = ?", (uid,))
        exists = c.fetchone() is not None
        
        if exists:
            c.execute("""
                UPDATE users SET 
                    fullName = ?,
                    email = ?,
                    role = ?,
                    status = ?,
                    treeTrackingNumber = ?,
                    createdAt = ?,
                    approvedAt = CASE WHEN ? = 'approved' THEN 
                        COALESCE(approvedAt, CURRENT_TIMESTAMP)
                    ELSE approvedAt END,
                    firebase_doc_id = ?,
                    last_sync_time = ?,
                    approved = ?
                WHERE uid = ?
            """, (
                user_data.get('fullName', ''),
                user_data.get('email', ''),
                user_data.get('role', 'individual'),
                user_data.get('status', 'pending'),
                user_data.get('treeTrackingNumber', ''),
                created_at,
                user_data.get('status', 'pending'),
                user_data.get('firebase_doc_id', ''),
                datetime.utcnow().isoformat(),
                user_data.get('approved', 0),
                uid
            ))
        else:
            c.execute("""
                INSERT INTO users (
                    fullName, email, uid, role, status, 
                    treeTrackingNumber, createdAt, approvedAt,
                    firebase_doc_id, last_sync_time, approved
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_data.get('fullName', ''),
                user_data.get('email', ''),
                uid,
                user_data.get('role', 'individual'),
                user_data.get('status', 'pending'),
                user_data.get('treeTrackingNumber', ''),
                created_at,
                user_data.get('approvedAt') if user_data.get('status') == 'approved' else None,
                user_data.get('firebase_doc_id', ''),
                datetime.utcnow().isoformat(),
                user_data.get('approved', 0)
            ))
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Error syncing user {uid} to SQL: {e}")
        return False
    finally:
        conn.close()

def send_email(recipient_email, subject, html_content):
    """Send an email using SMTP settings from secrets.toml"""
    try:
        # Get SMTP configuration from secrets
        smtp_server = st.secrets.get("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(st.secrets.get("SMTP_PORT", 587))
        smtp_username = st.secrets.get("SMTP_USERNAME", "")
        smtp_password = st.secrets.get("SMTP_PASSWORD", "")
        sender_email = st.secrets.get("SMTP_SENDER", smtp_username)
        
        if not smtp_username or not smtp_password:
            logger.warning("SMTP credentials not found in secrets.toml. Email not sent.")
            return False
            
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = sender_email
        message["To"] = recipient_email
        
        html_part = MIMEText(html_content, "html")
        message.attach(html_part)
        
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.sendmail(sender_email, recipient_email, message.as_string())
            
        logger.info(f"Email sent successfully to {recipient_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        return False
def send_approval_email(user_data):
    """Send approval email to user"""
    try:
        recipient_email = user_data.get("email")
        full_name = user_data.get("fullName", "User")
        tracking_number = user_data.get("treeTrackingNumber", "")
        app_url = st.secrets.get("APP_URL", "https://carbontally.app")
        
        template = EMAIL_TEMPLATES["approval"]
        subject = template["subject"]
        body = template["body"].format(
            fullName=full_name,
            treeTrackingNumber=tracking_number,
            app_url=app_url
        )
        
        return send_email(recipient_email, subject, body)
    except Exception as e:
        logger.error(f"Failed to send approval email: {str(e)}")
        return False

def send_rejection_email(user_data):
    """Send rejection email to user"""
    try:
        recipient_email = user_data.get("email")
        full_name = user_data.get("fullName", "User")
        
        template = EMAIL_TEMPLATES["rejection"]
        subject = template["subject"]
        body = template["body"].format(fullName=full_name)
        
        return send_email(recipient_email, subject, body)
    except Exception as e:
        logger.error(f"Failed to send rejection email: {str(e)}")
        return False

def generate_password_reset_link(email):
    """Generate a password reset link using Firebase Auth"""
    try:
        app_url = st.secrets.get("APP_URL", "https://your-app-url.com")
        
        action_code_settings = auth.ActionCodeSettings(
            url=f"{app_url}/reset-password",
            handle_code_in_app=False,
            dynamic_link_domain=None,
            android_package_name=None,
            android_minimum_version=None,
            android_install_app=None,
            iOS_bundle_id=None
        )
        
        reset_link = auth.generate_password_reset_link(
            email, 
            action_code_settings=action_code_settings
        )
        
        logger.info(f"Generated password reset link for {email}")
        return reset_link
    except auth.UserNotFoundError:
        logger.warning(f"Password reset requested for non-existent user: {email}")
        return None
    except Exception as e:
        logger.error(f"Error generating password reset link: {str(e)}")
        return None

def get_current_firebase_user():
    """Get the current authenticated Firebase user from session state"""
    return st.session_state.get('user', None)

def check_firebase_user_role(user, role):
    """Check if the current user has the specified role"""
    if user and 'role' in user:
        return user['role'] == role
    return False

def get_pending_users():
    """Get all pending users from the database"""
    conn = get_db_connection()
    try:
        return pd.read_sql_query("SELECT * FROM pending_users", conn).to_dict('records')
    except Exception as e:
        logger.error(f"Error loading pending users: {e}")
        return []
    finally:
        conn.close()

def get_approved_users():
    """Get all approved users from the database"""
    conn = get_db_connection()
    try:
        return pd.read_sql_query("SELECT * FROM users WHERE status = 'approved'", conn).to_dict('records')
    except Exception as e:
        logger.error(f"Error loading approved users: {e}")
        return []
    finally:
        conn.close()

def sync_users_from_firestore():
    """Sync users from Firestore to SQL database"""
    db = firestore.client()
    users_ref = db.collection("users")
    docs = users_ref.stream()

    conn = get_db_connection()
    cursor = conn.cursor()

    for doc in docs:
        data = doc.to_dict() or {}
        uid = str(data.get("uid", doc.id))
        fullName = str(data.get("fullName", ""))
        email = str(data.get("email", ""))
        role = str(data.get("role", "individual"))
        status = str(data.get("status", "pending"))
        tracking = data.get("treeTrackingNumber", "")
        tracking = "" if tracking is None else str(tracking)

        created_at = data.get("createdAt")
        if hasattr(created_at, "isoformat"):
            created_at = created_at.isoformat()
        else:
            created_at = str(created_at or datetime.utcnow().isoformat())

        approved_at = data.get("approvedAt")
        if hasattr(approved_at, "isoformat"):
            approved_at = approved_at.isoformat()
        else:
            approved_at = str(approved_at) if approved_at is not None else None

        firebase_doc_id = str(doc.id)
        last_sync_time = datetime.utcnow().isoformat()

        try:
            cursor.execute("""
                INSERT INTO users (
                    uid, fullName, email, role, status,
                    treeTrackingNumber, createdAt, approvedAt,
                    firebase_doc_id, last_sync_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                uid, fullName, email, role, status,
                tracking, created_at, approved_at,
                firebase_doc_id, last_sync_time
            ))
        except sqlite3.IntegrityError:
            cursor.execute("""
                UPDATE users SET
                    fullName = ?,
                    email = ?,
                    role = ?,
                    status = ?,
                    treeTrackingNumber = ?,
                    createdAt = ?,
                    approvedAt = ?,
                    last_sync_time = ?
                WHERE uid = ?
            """, (
                fullName, email, role, status,
                tracking, created_at, approved_at,
                last_sync_time,
                uid
            ))

    conn.commit()
    conn.close()
    logger.info("✅ Firebase → SQLite sync complete.")

def get_all_users():
    """Return all users from SQLite as a list of dicts, most recent first."""
    conn = None
    try:
        conn = get_db_connection()
        df = pd.read_sql_query(
            """
            SELECT
                uid,
                fullName,
                email,
                role,
                status,
                createdAt,
                approvedAt,
                treeTrackingNumber
            FROM users
            ORDER BY datetime(createdAt) DESC;
            """,
            conn
        )
        return df.to_dict('records')
    except Exception as e:
        logger.error(f"Error getting all users: {e}")
        return []
    finally:
        if conn:
            conn.close()

def approve_user(uid):
    """Approve user in both Firebase and SQL database"""
    try:
        db = initialize_firebase()
        if not db:
            return False

        user_ref = db.collection('users').document(uid)
        user_data = user_ref.get().to_dict()
        
        if not user_data:
            st.error("User not found in Firestore")
            return False

        # Update in Firestore
        user_ref.update({
            'status': 'approved',
            'approved': True,
            'approvedAt': firestore.SERVER_TIMESTAMP
        })

        # Sync to SQL
        user_data['status'] = 'approved'
        user_data['approved'] = True
        if not sync_user_to_sql(uid, user_data):
            st.error("Failed to sync user to SQL database")
            return False

        # Remove from pending users
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM pending_users WHERE uid = ?", (uid,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Error removing from pending_users: {e}")
        finally:
            conn.close()

        # Send approval email
        send_approval_email(user_data)
        
        return True
    except Exception as e:
        st.error(f"Error approving user: {e}")
        return False

def reject_user(uid):
    """Reject user and delete from all systems"""
    try:
        # Get user email before deleting for notification
        db = initialize_firebase()
        user_data = db.collection('users').document(uid).get().to_dict()
        
        # Delete from Firebase Auth
        auth.delete_user(uid)
        
        # Delete from Firestore
        if db:
            db.collection('users').document(uid).delete()
        
        # Delete from SQL databases
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM users WHERE uid = ?", (uid,))
            conn.execute("DELETE FROM pending_users WHERE uid = ?", (uid,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Error deleting user from SQL: {e}")
        finally:
            conn.close()
        
        # Send rejection email
        if user_data:
            send_rejection_email(user_data)
        
        return True
    except Exception as e:
        st.error(f"Error rejecting user: {e}")
        return False

def delete_user(uid: str):
    """Delete user from Firebase Auth and Firestore."""
    try:
        # Delete from Firebase Authentication
        auth.delete_user(uid)
        
        # Delete from Firestore
        db = initialize_firebase()
        if db:
            db.collection('users').document(uid).delete()
        
        # Delete from SQL database
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM users WHERE uid = ?", (uid,))
            conn.execute("DELETE FROM pending_users WHERE uid = ?", (uid,))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"Error deleting user from SQL: {e}")
            return False
        finally:
            conn.close()
            
    except auth.UserNotFoundError:
        logger.warning(f"User {uid} not found in Firebase Auth")
        return False
    except Exception as e:
        logger.error(f"Error deleting user {uid}: {e}")
        return False

def show_firebase_setup_guide():
    """Display instructions for setting up Firebase"""
    st.markdown("""
    ## Firebase Setup Guide
    
    1. Go to the [Firebase Console](https://console.firebase.google.com/)
    2. Create a new project or select an existing one
    3. Enable Authentication (Email/Password provider)
    4. Go to Project Settings > Service Accounts
    5. Generate a new private key (JSON) and download it
    6. Add the JSON content to your Streamlit secrets under 'FIREBASE_CONFIG'
    7. Get your Web API Key from Project Settings > General > Your apps
    8. Add the API key to your FIREBASE_CONFIG in secrets.toml
    
    For detailed instructions, see the [Firebase documentation](https://firebase.google.com/docs/admin/setup)
    """)
    st.stop()
