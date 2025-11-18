# kobo integration

# ========== STREAMLIT SETUP ==========
import streamlit as st

# ========== STANDARD LIBRARY IMPORTS ==========
import os
import sqlite3
import uuid  # Imported but not directly used for generating form_uuid; KoBo provides it.
import base64
import json
from pathlib import Path
from datetime import datetime
from io import BytesIO
import logging

# ========== THIRD-PARTY IMPORTS ==========
import pandas as pd
import qrcode
from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests

# Configure logging for this module
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== CONFIGURATION & DIRECTORY SETUP ==========
BASE_DIR = Path(__file__).parent if "__file__" in locals() else Path.cwd()
DATA_DIR = BASE_DIR / "data"
SQLITE_DB = DATA_DIR / "trees.db"
QR_CODE_DIR = DATA_DIR / "qr_codes"

# Ensure directories exist with robust error handling
try:
    DATA_DIR.mkdir(exist_ok=True, parents=True)
    QR_CODE_DIR.mkdir(exist_ok=True, parents=True)
except OSError as e:
    st.error(f"CRITICAL ERROR: Failed to create necessary application directories. Please ensure the drive ({BASE_DIR.anchor}) is accessible and you have write permissions. Error: {e}")
    st.stop()
except Exception as e:
    st.error(f"An unexpected error occurred during directory creation: {e}")
    st.stop()

KOBO_API_URL = "https://kf.kobotoolbox.org/api/v2"
# These will be initialized from secrets/env vars
KOBO_API_TOKEN = None
KOBO_ASSET_ID = None
KOBO_MONITORING_FORM_CODE = None
KOBO_PLANTING_FORM_CODE = None

# ========== LOCAL HELPERS ==========
def get_db_connection():
    """Establishes a connection to the SQLite database."""
    return sqlite3.connect(SQLITE_DB)

# ========== CORE DATABASE FUNCTIONS ==========

def initialize_database():
    """
    Initializes the SQLite database and creates the 'trees' and 'sequences' tables
    with the correct schema.
    """
    conn = get_db_connection()
    try:
        c = conn.cursor()

        # Create 'trees' table with all necessary columns
        # tree_id TEXT PRIMARY KEY: Unique identifier for the logical tree instance.
        # form_uuid TEXT UNIQUE NOT NULL: Unique identifier for the specific KoBo submission.
        # treeTrackingNumber TEXT: Identifier linking multiple KoBo submissions to one logical tree.
        c.execute('''
            CREATE TABLE IF NOT EXISTS trees (
                tree_id TEXT PRIMARY KEY,
                local_name TEXT,
                scientific_name TEXT,
                planters_name TEXT,
                date_planted TEXT,
                latitude REAL,
                longitude REAL,
                co2_kg REAL,
                planter_email TEXT,
                planter_uid TEXT,
                treeTrackingNumber TEXT,
                dbh_cm REAL,
                rcd_cm REAL,
                height_m REAL,
                tree_stage TEXT,
                status TEXT,
                country TEXT,
                county TEXT,
                sub_county TEXT,
                ward TEXT,
                adopter_name TEXT,
                last_updated TEXT,
                institution TEXT,
                form_uuid TEXT UNIQUE NOT NULL
            )
        ''')

        # Create index on treeTrackingNumber for faster queries, especially for lookups
        c.execute('''
            CREATE INDEX IF NOT EXISTS idx_tree_tracking_number 
            ON trees (treeTrackingNumber)
        ''')

        # Create 'sequences' table for tree ID generation
        c.execute("""
            CREATE TABLE IF NOT EXISTS sequences (
                prefix TEXT PRIMARY KEY,
                next_val INTEGER
            )
        """)
        conn.commit()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        st.error(f"Database initialization failed: {e}")
    finally:
        if conn:
            conn.close()

def get_next_tree_id(user_full_name: str, treeTrackingNumber: str, form_uuid: str) -> str:
    """Generate a unique tree ID using initials + sequence or return existing ID for form_uuid"""
    conn = sqlite3.connect(SQLITE_DB)
    try:
        c = conn.cursor()

        # First check if we already have a tree with this form_uuid
        c.execute("SELECT tree_id FROM trees WHERE form_uuid = ?", (form_uuid,))
        existing_id = c.fetchone()
        if existing_id:
            return existing_id[0]  # Return existing ID for this form submission

        # Generate a new ID for new submissions (even with same tracking number)
        parts = user_full_name.strip().upper().split()
        if len(parts) >= 2:
            prefix = parts[0][0] + parts[1][0]
        elif len(parts) == 1:
            prefix = parts[0][:2]
        else:
            prefix = "TR"  # Default prefix if no name

        # Get current sequence number for this prefix
        c.execute("SELECT next_val FROM sequences WHERE prefix = ?", (prefix,))
        row = c.fetchone()
        next_val = row[0] if row else 1

        # Format suffix with 3 digits
        suffix = f"{next_val:03d}"
        tree_id = f"{prefix}{suffix}"

        # Update sequence for next time
        if row:
            c.execute("UPDATE sequences SET next_val = ? WHERE prefix = ?", 
                     (next_val + 1, prefix))
        else:
            c.execute("INSERT INTO sequences (prefix, next_val) VALUES (?, ?)", 
                     (prefix, next_val + 1))

        conn.commit()
        return tree_id

    except Exception as e:
        conn.rollback()
        logging.error(f"Error generating tree ID: {e}")
        # Fallback to UUID if sequence generation fails
        return f"TR{str(uuid.uuid4())[:8]}"
    finally:
        conn.close()
def save_tree_data(tree_data):
    """Saves new tree data to the database"""
    required_fields = ['tree_id', 'local_name', 'form_uuid', 'treeTrackingNumber']
    for field in required_fields:
        if field not in tree_data or not tree_data[field]:
            raise ValueError(f"Missing required field: {field}")

    conn = get_db_connection()
    try:
        # Use INSERT OR REPLACE to handle updates
        columns = ', '.join(tree_data.keys())
        placeholders = ':' + ', :'.join(tree_data.keys())
        sql = f"INSERT OR REPLACE INTO trees ({columns}) VALUES ({placeholders})"
        
        conn.execute(sql, tree_data)
        conn.commit()
        logger.info(f"Saved tree {tree_data['tree_id']} (Form: {tree_data['form_uuid']})")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving tree data: {e}")
        raise
    finally:
        conn.close()
def get_tree_metrics():
    """Return comprehensive tree metrics for dashboards."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        c.execute("SELECT COUNT(*) FROM trees")
        total_trees = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM trees WHERE status = 'Alive'")
        alive_trees = c.fetchone()[0]
        
        c.execute("SELECT SUM(co2_kg) FROM trees")
        total_co2 = c.fetchone()[0] or 0.0 # Use 0.0 if SUM returns None (no trees)
        
        c.execute("""
            SELECT tree_id, local_name, planters_name, date_planted, latitude, longitude 
            FROM trees 
            ORDER BY date_planted DESC 
            LIMIT 5
        """)
        recent_trees = c.fetchall()
        
        c.execute("""
            SELECT scientific_name, COUNT(*) as count 
            FROM trees 
            GROUP BY scientific_name 
            ORDER BY count DESC
        """)
        species_dist = c.fetchall()
        
        survival_rate = round((alive_trees / total_trees * 100), 1) if total_trees > 0 else 0
        
        return {
            'total_trees': total_trees,
            'alive_trees': alive_trees,
            'total_co2': round(total_co2, 2),
            'recent_trees': recent_trees,
            'species_dist': species_dist,
            'survival_rate': survival_rate
        }
    except Exception as e:
        logger.error(f"Error fetching tree metrics: {e}", exc_info=True)
        st.error(f"Error fetching metrics: {e}")
        return None
    finally:
        if conn:
            conn.close()

# ========== KOBO TOOLBOX INTEGRATION FUNCTIONS ==========

def initialize_kobo_credentials():
    """Initializes KoBo API credentials from Streamlit secrets or environment variables."""
    global KOBO_API_TOKEN, KOBO_ASSET_ID, KOBO_MONITORING_FORM_CODE, KOBO_PLANTING_FORM_CODE
    
    # Check if already initialized to avoid redundant calls
    if KOBO_API_TOKEN is not None:
        return KOBO_API_TOKEN, KOBO_ASSET_ID, KOBO_MONITORING_FORM_CODE, KOBO_PLANTING_FORM_CODE

    try:
        KOBO_API_TOKEN = st.secrets["KOBO_API_TOKEN"]
        KOBO_ASSET_ID = st.secrets["KOBO_ASSET_ID"]
        # Use .get() for optional secrets, providing a sensible default
        KOBO_MONITORING_FORM_CODE = st.secrets.get("KOBO_MONITORING_FORM_CODE", "dXdb36aV") # Example placeholder, update with your actual code
        KOBO_PLANTING_FORM_CODE = st.secrets.get("KOBO_PLANTING_FORM_CODE", "s8ntxUM5") # Example placeholder, update with your actual code
        logger.info("KoBo API credentials loaded from Streamlit secrets.")
    except (AttributeError, KeyError) as e:
        logger.warning(f"Streamlit secrets not fully configured: {e}. Trying environment variables.")
        KOBO_API_TOKEN = os.getenv('KOBO_API_TOKEN', '')
        KOBO_ASSET_ID = os.getenv('KOBO_ASSET_ID', '')
        KOBO_MONITORING_FORM_CODE = os.getenv('KOBO_MONITORING_FORM_CODE', "dXdb36aV") # Example placeholder
        KOBO_PLANTING_FORM_CODE = os.getenv('KOBO_PLANTING_FORM_CODE', "s8ntxUM5") # Example placeholder
        if KOBO_API_TOKEN and KOBO_ASSET_ID:
            logger.info("KoBo API credentials loaded from environment variables.")
        else:
            logger.error(f"KoBo API credentials (API Token or Asset ID) are missing from both Streamlit secrets and environment variables.")
            error_msg = "KoBo API credentials (API Token or Asset ID) are missing or not configured. Please check Streamlit secrets or environment variables."
            st.error(error_msg)
            raise ValueError(error_msg) # Propagate the error to stop execution if critical

    if not KOBO_API_TOKEN or KOBO_API_TOKEN == 'your_api_token_here' or not KOBO_ASSET_ID or KOBO_ASSET_ID == 'your_asset_id_here':
        error_msg = "KoBo API credentials (API Token or Asset ID) are missing or are placeholder values."
        logger.error(error_msg)
        st.error(error_msg)
        raise ValueError(error_msg)
    
    if not KOBO_MONITORING_FORM_CODE or KOBO_MONITORING_FORM_CODE == 'placeholder_form_code' or KOBO_MONITORING_FORM_CODE == 'dXdb36aV':
        logger.warning("KOBO_MONITORING_FORM_CODE is not configured or is a placeholder. QR codes for monitoring might use a default.")
        
    if not KOBO_PLANTING_FORM_CODE or KOBO_PLANTING_FORM_CODE == 'placeholder_form_code' or KOBO_PLANTING_FORM_CODE == 's8ntxUM5':
        logger.warning("KOBO_PLANTING_FORM_CODE is not configured or is a placeholder.")

    return KOBO_API_TOKEN, KOBO_ASSET_ID, KOBO_MONITORING_FORM_CODE, KOBO_PLANTING_FORM_CODE

def get_kobo_secrets():
    """Helper to get all KoBo secrets/configs, ensuring they are initialized."""
    try:
        api_token, asset_id, monitoring_form_code, planting_form_code = initialize_kobo_credentials()
        return api_token, asset_id, monitoring_form_code, planting_form_code
    except Exception as e:
        logger.error(f"Error in get_kobo_secrets: {e}", exc_info=True)
        return None, None, None, None

def get_kobo_submissions(asset_id):
    """Fetches all submissions for a given KoBo asset ID."""
    api_token, _, _, _ = get_kobo_secrets()
    if not api_token:
        # Error already logged by get_kobo_secrets/initialize_kobo_credentials
        return None

    headers = {"Authorization": f"Token {api_token}"}
    all_submissions = []
    next_url = f"{KOBO_API_URL}/assets/{asset_id}/data/"
    
    try:
        while next_url:
            response = requests.get(next_url, headers=headers, params={"format": "json"})
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            data = response.json()
            all_submissions.extend(data.get('results', []))
            next_url = data.get('next')
        logger.info(f"Successfully fetched {len(all_submissions)} submissions for asset ID: {asset_id}")
        return {'results': all_submissions}
    except requests.exceptions.RequestException as e:
        logger.error(f"Network or API error fetching submissions for asset ID {asset_id}: {e}", exc_info=True)
        st.error(f"Error fetching submissions from KoBoToolbox. Please check your internet connection or API credentials. Details: {str(e)}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"JSON decoding error from KoBoToolbox response for asset ID {asset_id}: {e}", exc_info=True)
        st.error(f"Error processing KoBoToolbox response. Details: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while fetching KoBo submissions for asset ID {asset_id}: {e}", exc_info=True)
        st.error(f"An unexpected error occurred while fetching KoBo submissions: {str(e)}")
        return None

def check_for_new_submissions():
    """Checks KoBoToolbox for new tree submissions, processes them, saves them to DB."""
    try:
        api_token, asset_id, monitoring_form_code, planting_form_code = initialize_kobo_credentials()
        
        if not asset_id:
            return []

        current_user = st.session_state.get('user', {})
        user_tracking_number = current_user.get('treeTrackingNumber')
        user_full_name = current_user.get('fullName', current_user.get('displayName', ''))

        if st.session_state.get('user', {}).get('user_type') != 'admin' and not user_tracking_number:
            st.error("User tracking number not found in session.")
            logger.warning("User treeTrackingNumber missing from session_state for non-admin user.")
            return []

        submissions_data = get_kobo_submissions(asset_id)
        if not submissions_data or 'results' not in submissions_data:
            st.info("No submissions found in KoBoToolbox or failed to fetch.")
            return []

        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT form_uuid FROM trees")
        saved_uuids = {row[0] for row in c.fetchall()}
        if conn:
            conn.close()

        processed_trees = []
        for submission in submissions_data['results']:
            form_uuid = submission.get('_uuid')
            
            if not form_uuid:
                continue
            
            # Skip if we've already processed this exact form submission
            if form_uuid in saved_uuids:
                continue
                
            submission_tracking = submission.get('treeTrackingNumber')

            # Filter submissions based on user's tracking number, unless admin
            if (st.session_state.get('user', {}).get('user_type') != 'admin' and 
                submission_tracking != user_tracking_number):
                continue

            try:
                tree_data = map_kobo_to_database(submission, current_user)
                save_tree_data(tree_data)
                
                qr_path = generate_qr_code(
                    tree_id=tree_data["tree_id"],
                    tree_tracking_number=tree_data["treeTrackingNumber"],
                    tree_name=tree_data["local_name"],
                    planter=tree_data["planters_name"],
                    date_planted=tree_data["date_planted"]
                )
                
                processed_trees.append({
                    "data": tree_data,
                    "qr_code_path": qr_path
                })
                
            except Exception as e:
                logger.error(f"Error processing KoBo submission {form_uuid}: {str(e)}", exc_info=True)
                continue

        return processed_trees

    except Exception as e:
        logger.error(f"Failed to check submissions: {str(e)}", exc_info=True)
        st.error(f"Failed to check submissions: {str(e)}")
        return []
def map_kobo_to_database(submission, current_user):
    """Maps KoBo submission data to the database schema with consistent treeTrackingNumber."""
    geolocation = submission.get('_geolocation', [None, None])

    if isinstance(geolocation, str):
        try:
            geolocation = json.loads(geolocation)
        except json.JSONDecodeError:
            logger.warning(f"Could not decode _geolocation string: {geolocation}")
            geolocation = [None, None]
    
    # Ensure geolocation is a list of at least two elements, or set to None
    latitude = float(geolocation[0]) if geolocation and len(geolocation) > 0 and geolocation[0] is not None else None
    longitude = float(geolocation[1]) if geolocation and len(geolocation) > 1 and geolocation[1] is not None else None

    # Determine planter's name, prioritizing submission data, then user session, then fallback
    planters_name = submission.get('planters_name', current_user.get('fullName', current_user.get('displayName', 'Unknown')))
    
    # Determine treeTrackingNumber, prioritizing submission data, then user session, then fallback
    treeTrackingNumber = submission.get('treeTrackingNumber', current_user.get('treeTrackingNumber', 'UNKNOWN'))
    if not treeTrackingNumber or treeTrackingNumber == 'UNKNOWN':
        # This can happen if neither KoBo submission nor user session has a valid tracking number
        logger.warning(f"treeTrackingNumber is missing or 'UNKNOWN' in submission {submission.get('_id', 'N/A')}. This might lead to new tree IDs for logical updates.")
        # For simplicity, we'll continue, but a robust app might require it.
        # raise ValueError("Invalid treeTrackingNumber - cannot be empty or 'UNKNOWN' from submission or user data.")

    form_uuid = submission.get('_uuid')
    if not form_uuid:
        logger.error(f"KoBo Submission ID {submission.get('_id', 'N/A')} has no _uuid. Cannot process.")
        raise ValueError("Missing required '_uuid' in KoBo submission.")

    # Generate tree ID (this function now handles existing IDs via form_uuid or treeTrackingNumber)
    tree_id = get_next_tree_id(planters_name, treeTrackingNumber, form_uuid)

    local_name = submission.get('local_name', 'Unknown')
    scientific_name = submission.get('scientific_name', 'Unknown')
    date_planted = submission.get('date_planted', datetime.now().isoformat())

    try:
        # Normalize date_planted to 'YYYY-MM-DD' format
        if isinstance(date_planted, str):
            # Handle potential 'Z' for UTC or just date strings
            # Only try to parse if it looks like a full datetime string, otherwise use as is
            if 'T' in date_planted or '+' in date_planted or 'Z' in date_planted:
                date_obj = datetime.fromisoformat(date_planted.replace('Z', '+00:00') if 'Z' in date_planted else date_planted)
                date_planted = date_obj.strftime('%Y-%m-%d')
            else: # Assume it's already a date string like 'YYYY-MM-DD'
                datetime.strptime(date_planted, '%Y-%m-%d') # Validate format
    except ValueError:
        logger.warning(f"Could not parse date_planted '{date_planted}'. Using current date for tree_id {tree_id}.")
        date_planted = datetime.now().strftime('%Y-%m-%d')

    # Convert numeric fields, handling potential missing values or bad types gracefully
    dbh_cm = float(submission.get('dbh_cm')) if submission.get('dbh_cm') is not None else None
    height_m = float(submission.get('height_m')) if submission.get('height_m') is not None else None
    rcd_cm = float(submission.get('rcd_cm')) if submission.get('rcd_cm') is not None else None

    status = submission.get('status', 'Planted')
    tree_stage = submission.get('tree_stage', 'Sapling')
    country = submission.get('country', 'Unknown')
    county = submission.get('county', 'Unknown')
    sub_county = submission.get('sub_county', 'Unknown')
    ward = submission.get('ward', 'Unknown')
    adopter_name = submission.get('adopter_name', '')
    institution = submission.get('institution', current_user.get('institution', 'Unknown'))

    return {
        'tree_id': tree_id,
        'local_name': local_name,
        'scientific_name': scientific_name,
        'planters_name': planters_name,
        'date_planted': date_planted,
        'latitude': latitude,
        'longitude': longitude,
        'co2_kg': calculate_co2_sequestered(dbh_cm, height_m),
        'planter_email': current_user.get('email', ''), # Assuming planter email comes from current_user session
        'planter_uid': current_user.get('uid', ''), # Assuming planter UID comes from current_user session
        'treeTrackingNumber': treeTrackingNumber,
        'dbh_cm': dbh_cm,
        'rcd_cm': rcd_cm,
        'height_m': height_m,
        'tree_stage': tree_stage,
        'status': status,
        'country': country,
        'county': county,
        'sub_county': sub_county,
        'ward': ward,
        'adopter_name': adopter_name,
        'last_updated': datetime.utcnow().isoformat(), # Use UTC for consistency
        'institution': institution,
        'form_uuid': form_uuid
    }

def calculate_co2_sequestered(dbh_cm, height_m):
    """
    Calculates CO2 sequestered based on DBH and Height.
    This is a placeholder formula. For real-world applications,
    use scientifically validated allometric equations specific to species and region.
    """
    if dbh_cm is None or height_m is None or dbh_cm <= 0 or height_m <= 0:
        return 0.0
        
    # Example simplified formula (not scientifically rigorous):
    # This formula appears to be an attempt at:
    # 0.25 * pi * (DBH_m)^2 * Height_m * Wood_Density * Carbon_Fraction * CO2_conversion
    # Assuming:
    # 0.25 is a form factor/conversion factor
    # 3.14159 is pi
    # (dbh_cm / 100)^2 converts cm to meters and squares it
    # height_m is in meters
    # 600 kg/m^3 is an approximate wood density (e.g., for some hardwoods)
    # 0.5 is an approximate carbon fraction of biomass
    # 3.67 is the conversion factor from Carbon to CO2 (44/12)
    return 0.25 * 3.14159 * (dbh_cm / 100)**2 * height_m * 600 * 0.5 * 3.67

# ========== QR CODE GENERATION ==========

def generate_qr_code(tree_id, tree_tracking_number=None, tree_name=None, planter=None, date_planted=None):
    """Generate QR code with prefilled KoBo URL and labels"""
    try:
        _, _, monitoring_form_code, _ = get_kobo_secrets()
        
        # Determine the base URL for the KoBo form to be linked via QR.
        # This typically points to the monitoring form where the tree ID is used for tracking.
        # Use the KOBO_MONITORING_FORM_CODE if available, otherwise a generic one.
        kobo_form_endpoint = f"https://ee.kobotoolbox.org/x/{monitoring_form_code}" if monitoring_form_code else "https://ee.kobotoolbox.org/x/your_monitoring_form_code_here"

        # Use tracking number for the URL parameter if provided, otherwise fallback to tree_id.
        # This assumes your KoBo monitoring form has a question named 'tree_id' that you want to pre-fill.
        tracking_param_value = tree_tracking_number if tree_tracking_number and tree_tracking_number != 'UNKNOWN' else tree_id

        # Construct KoBo URL with optional prefill parameters for the monitoring form
        params = f"?tree_id={requests.utils.quote(str(tracking_param_value))}" # URL-encode the tracking value
        if tree_name:
            params += f"&name={requests.utils.quote(tree_name)}"
        if planter:
            params += f"&planter={requests.utils.quote(planter)}"
        if date_planted:
            params += f"&date_planted={requests.utils.quote(date_planted)}"
        
        form_url = kobo_form_endpoint + params

        logger.info(f"Generating QR code for Tree ID: {tree_id} (Tracking: {tracking_param_value}) with URL: {form_url}")

        # Create green QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(form_url)
        qr.make(fit=True)

        # Generate image with labels
        qr_img = qr.make_image(fill_color="#2e8b57", back_color="white").convert('RGB')
        width, qr_height = qr_img.size

        # Increase height for text labels
        text_height_addition = 60
        img = Image.new('RGB', (width, qr_height + text_height_addition), 'white')
        img.paste(qr_img, (0, 0)) # Paste QR code at the top

        draw = ImageDraw.Draw(img)

        # Try to load a true type font, fall back to default if not found
        try:
            # Look for a common font, adjust path for your OS if needed
            # On Windows: "arial.ttf"
            # On Linux (often): "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            # On macOS: "/Library/Fonts/Arial Unicode.ttf" or "arial.ttf"
            font_path_candidates = [
                "arial.ttf", # Windows
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", # Common Linux
                "/Library/Fonts/Arial Unicode.ttf", # macOS
                "/System/Library/Fonts/Supplemental/Arial.ttf" # macOS newer versions
            ]
            
            selected_font_path = None
            for fp in font_path_candidates:
                if Path(fp).exists():
                    selected_font_path = fp
                    break

            if selected_font_path:
                font = ImageFont.truetype(selected_font_path, 16)
            else:
                font = ImageFont.load_default()
                logger.warning("Could not find common system font. Using default PIL font.")
        except Exception as font_e:
            font = ImageFont.load_default()
            logger.warning(f"Error loading custom font: {font_e}. Using default PIL font.")

        # Text labels below the QR code
        draw.text((10, qr_height + 10), f"Tree ID: {tree_id}", fill="black", font=font)
        draw.text((10, qr_height + 35), "Powered by CarbonTally", fill="gray", font=font)

        # Save using Tree ID as filename
        QR_CODE_DIR.mkdir(exist_ok=True, parents=True) # Ensure directory exists
        file_path = QR_CODE_DIR / f"{tree_id}.png"
        img.save(file_path)

        return str(file_path)
    except Exception as e:
        logger.error(f"QR generation failed for tree_id {tree_id}: {e}", exc_info=True)
        st.error(f"QR generation failed for Tree ID {tree_id}: {e}")
        return None

# ========== STREAMLIT UI COMPONENTS ==========

def display_tree_results(tree_results):
    """Displays the results of newly processed trees with QR codes."""
    st.markdown("## 🌿 Newly Processed Trees (or Updates)")

    if not tree_results:
        st.info("No new tree submissions processed for display.")
        return

    for idx, tree in enumerate(tree_results):
        data = tree["data"]
        tree_id = data.get("tree_id", "Unknown")
        tree_name = data.get("local_name", "Unknown")
        planter = data.get("planters_name", "Unknown")
        date_planted = data.get("date_planted", "Unknown")
        tracking_number = data.get("treeTrackingNumber", "N/A")

        # Check if QR code path exists, regenerate if not (e.g., on app re-run or first load)
        qr_path = tree.get("qr_code_path")
        if not qr_path or not Path(qr_path).exists():
            qr_path = generate_qr_code(
                tree_id=tree_id,
                tree_tracking_number=tracking_number,
                tree_name=tree_name,
                planter=planter,
                date_planted=date_planted
            )
            tree["qr_code_path"] = qr_path # Update the dictionary for subsequent display/download

        with st.expander(f"🌳 Tree ID: {tree_id} | Tracking #: {tracking_number}"):
            col1, col2 = st.columns([2, 1])

            with col1:
                st.markdown(f"**🧾 Local Name:** {tree_name}")
                st.markdown(f"**🔬 Scientific Name:** {data.get('scientific_name', 'Unknown')}")
                st.markdown(f"**👤 Planted by:** {planter}")
                st.markdown(f"**📅 Date Planted:** {date_planted}")
                st.markdown(f"**🌱 CO₂ Sequestered:** {data.get('co2_kg', 0.0):.2f} kg")
                st.markdown(f"**📍 Latitude:** {data.get('latitude', 'N/A')}")
                st.markdown(f"**📍 Longitude:** {data.get('longitude', 'N/A')}")
                st.markdown(f"**🌳 Tree Stage:** {data.get('tree_stage', 'N/A')}")
                st.markdown(f"**📊 Status:** {data.get('status', 'N/A')}")
                st.markdown(f"**🌍 Country:** {data.get('country', 'N/A')}")
                st.markdown(f"**🏙️ County:** {data.get('county', 'N/A')}")
                st.markdown(f"**🏡 Sub-County:** {data.get('sub_county', 'N/A')}")
                st.markdown(f"**🏘️ Ward:** {data.get('ward', 'N/A')}")
                st.markdown(f"**🤝 Adopter Name:** {data.get('adopter_name', 'N/A')}")
                st.markdown(f"**🏢 Institution:** {data.get('institution', 'N/A')}")
                st.markdown(f"**Last Updated (UTC):** {data.get('last_updated', 'N/A')}")
                st.markdown(f"**KoBo Form UUID:** `{data.get('form_uuid', 'N/A')}`")


            with col2:
                if qr_path and Path(qr_path).exists():
                    st.image(str(qr_path), caption="Tree QR Code", width=200)
                    with open(qr_path, "rb") as qr_file:
                        qr_data = qr_file.read()
                    st.download_button(
                        label="📥 Download QR Code",
                        data=qr_data,
                        file_name=f"tree_{tracking_number}_{tree_id}_qrcode.png",
                        mime="image/png",
                        key=f"qr_download_{idx}"
                    )
                else:
                    st.warning("QR code not available.")

# ========== STREAMLIT UI SECTIONS ==========

def plant_a_tree_section():
    """Streamlit UI for the 'Plant a Tree' functionality, focused on checking submissions."""
    st.title("🌳 Plant a Tree (KoBoToolbox Integration)")
    
    # Initialize session state variables if they don't exist
    if "tree_results" not in st.session_state:
        st.session_state.tree_results = None
    if "last_checked" not in st.session_state:
        st.session_state.last_checked = None

    st.markdown("### Check for New Tree Submissions")
    st.write("This section fetches new tree planting or monitoring submissions from your configured KoBoToolbox project.")
    st.write("Only submissions matching your user's `treeTrackingNumber` (if not an admin) and not yet processed will be shown.")
    st.write("Ensure you have already filled out and submitted the tree form through KoBoToolbox.")
    st.write("Click the button below to check for your submissions and generate/update tree records and QR codes.")
    
    # Current user info for debugging/clarity
    current_user_info = st.session_state.get('user', {})
    st.info(f"Logged in as: **{current_user_info.get('fullName', 'N/A')}** "
            f"(Type: **{current_user_info.get('user_type', 'N/A')}**, "
            f"Tracking No: **{current_user_info.get('treeTrackingNumber', 'N/A')}**)")

    if st.button("Check for New Submissions", key="check_submissions_btn_main"):
        with st.spinner("Checking for new tree submissions... This may take a moment."):
            st.session_state.tree_results = check_for_new_submissions()
            st.session_state.last_checked = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.rerun() # Rerun to refresh the display immediately after processing

    if st.session_state.last_checked:
        st.caption(f"Last checked: {st.session_state.last_checked}")

    if st.session_state.tree_results is not None: # Use 'is not None' because it could be an empty list
        if len(st.session_state.tree_results) > 0:
            st.success(f"Found and processed {len(st.session_state.tree_results)} new/updated tree record(s)!")
            display_tree_results(st.session_state.tree_results)
        else:
            st.info("No new tree submissions found matching your criteria. This could be because:")
            st.markdown("- You haven't submitted a new form in KoBoToolbox.")
            st.markdown("- The forms submitted do not match your `treeTrackingNumber` (if you are not an admin).")
            st.markdown("- All relevant forms have already been processed.")
            
        # Add a refresh button to clear results and allow re-checking
        if st.button("Clear Display & Re-check Submissions", key="refresh_submissions_btn"):
            st.session_state.tree_results = None
            st.session_state.last_checked = None
            st.rerun() # Use rerun here to reset the UI effectively

def display_dashboard():
    """Displays key metrics and visualizations of tree data."""
    st.title("📊 Tree Planting Dashboard")

    metrics = get_tree_metrics()

    if metrics:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("🌳 Total Trees Planted", metrics['total_trees'])
        with col2:
            st.metric("💚 Alive Trees", metrics['alive_trees'])
        with col3:
            st.metric("💨 Total CO₂ Sequestered", f"{metrics['total_co2']} kg")
        
        st.metric("🌱 Overall Survival Rate", f"{metrics['survival_rate']}%")

        st.subheader("Recent Plantings")
        if metrics['recent_trees']:
            df_recent = pd.DataFrame(metrics['recent_trees'], columns=['Tree ID', 'Local Name', 'Planter', 'Date Planted', 'Latitude', 'Longitude'])
            st.dataframe(df_recent)
        else:
            st.info("No recent tree plantings to display.")

        st.subheader("Species Distribution")
        if metrics['species_dist']:
            df_species = pd.DataFrame(metrics['species_dist'], columns=['Scientific Name', 'Count'])
            st.bar_chart(df_species.set_index('Scientific Name'))
        else:
            st.info("No species data to display.")
    else:
        st.warning("Could not load tree metrics. Database might be empty or an error occurred. Please check the 'Plant a Tree' section to process submissions.")

# ========== MAIN APPLICATION LOGIC ==========
def main():
    st.set_page_config(
        page_title="CarbonTally Tree Tracking",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # Simulate authentication state and user session for this standalone example
    # In a real app, this would come from a proper authentication system.
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = True # Assume authenticated for this example
    if 'user' not in st.session_state:
        # This mock user is essential for the `check_for_new_submissions` function to work
        # and to demonstrate the 'treeTrackingNumber' filtering.
        st.session_state.user = {
            "username": "demo_planter",
            "user_type": "field", # Change to "admin" to process all submissions, or "field" to filter by treeTrackingNumber
            "email": "planter.demo@example.com",
            "fullName": "Demo Planter", # Used for generating tree IDs prefix
            "displayName": "Demo Planter",
            "institution": "Demo Org",
            "treeTrackingNumber": "DEMO-TRK-001", # <--- IMPORTANT: SET THIS TO A TRACKING NUMBER USED IN YOUR KOBO FORMS FOR TESTING!
            "uid": "demo_uid_123"
        }
        logger.info(f"Initialized mock user session for standalone run: {st.session_state.user['treeTrackingNumber']}")
    else:
        logger.info(f"User session already exists: {st.session_state.user.get('treeTrackingNumber', 'N/A')}")
        
    # Initialize KoBo credentials early to catch configuration errors
    try:
        initialize_kobo_credentials()
    except ValueError as e:
        st.error(f"Application cannot start due to KoBo API configuration error: {e}. Please check your `.streamlit/secrets.toml` or environment variables.")
        st.stop() # Stop the app if critical credentials are missing

    initialize_database() # Ensure database is set up on app start

    st.sidebar.title("CarbonTally")
    
    # Navigation
    menu = ["Plant a Tree", "Dashboard"]
    choice = st.sidebar.radio("Navigation", menu)

    if st.session_state.authenticated:
        if choice == "Plant a Tree":
            plant_a_tree_section()
        elif choice == "Dashboard":
            display_dashboard()
    else:
        st.warning("Please log in to access the application.")
        # In a real application, you would implement a proper login mechanism here.

if __name__ == "__main__":
    main()
