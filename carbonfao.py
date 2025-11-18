import os
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from pathlib import Path

# =========================================================
# ---------------------- CONFIG ---------------------------
# =========================================================

BASE_DIR = Path(__file__).parent 

# FIX: Point the AEZ variable to the existing GEZ file path 
# ('gez2010') to resolve the pyogrio.errors.DataSourceError.
AEZ_SHAPEFILE_PATH = os.path.join(BASE_DIR, "data", "gez2010", "gez_2010_wgs84.shp")

# Load FAO Agro-Ecological Zones GeoDataFrame
try:
    FAO_AEZ_GDF = gpd.read_file(AEZ_SHAPEFILE_PATH)
except Exception as e:
    # A simplified error message if the file is still missing
    print(f"Error loading AEZ shapefile: {e}")
    # Initialize as an empty GeoDataFrame to prevent script crash
    FAO_AEZ_GDF = gpd.GeoDataFrame() 


# === Load Species-Specific Allometric Coefficients ===
SPECIES_CSV_PATH = os.path.join(BASE_DIR, "data", "species_allometrics.csv")
# Load and preprocess the allometric coefficients CSV
try:
    SPECIES_ALLOMETRIC_DF = pd.read_csv(SPECIES_CSV_PATH)
    SPECIES_ALLOMETRIC = {
        row["species"].strip().lower(): {"a": row["a"], "b": row["b"], "c": row["c"]}
        for _, row in SPECIES_ALLOMETRIC_DF.iterrows()
    }
except FileNotFoundError:
    print(f"Warning: Species allometrics file not found at {SPECIES_CSV_PATH}. Using default coefficients only.")
    SPECIES_ALLOMETRIC = {}


# =========================================================
# ------------------ AEZ LOOKUP FUNCTIONS -----------------
# =========================================================

def get_agro_ecological_zone(lat, lon, gdf=FAO_AEZ_GDF):
    """
    Determine FAO Agro-Ecological Zone (AEZ) using geopandas shapefile lookup.
    Returns zone name/code from 'gez_name' column (or similar).
    """
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or gdf.empty:
        return None
    
    try:
        point = Point(lon, lat)
        match = gdf[gdf.geometry.contains(point)]
        
        if not match.empty:
            # Assuming 'gez_name' is the relevant column in the gez_2010_wgs84.shp file
            return match.iloc[0]["gez_name"] 
    except Exception:
        # Handle CRS or other spatial errors gracefully
        return None
        
    return None

def get_aez_coefficients(aez_identifier=None, species=None):
    """
    Get biomass coefficients (a, b, c) from species lookup, 
    or fallback to Agro-Ecological Zone (AEZ) specific defaults.
    """
    # 1. Safely clean species name for lookup
    species_key = species.strip().lower() if isinstance(species, str) else ""

    # 2. Lookup species-specific coefficients (Priority 1)
    if species_key in SPECIES_ALLOMETRIC:
        return SPECIES_ALLOMETRIC[species_key]

    # 3. Fallback to Agro-Ecological Zone (AEZ) specific coefficients (Priority 2)
    # NOTE: These names/codes and coefficients are examples for AEZ groupings.
    aez_table = {
        "Tropical Rainforest": {"a": 0.0509, "b": 2.4, "c": 1.0},
        "Tropical Moist Forest": {"a": 0.060, "b": 2.3, "c": 1.0},
        "Tropical Dry Forest": {"a": 0.045, "b": 2.5, "c": 1.0},
        "Temperate Forest": {"a": 0.034, "b": 2.6, "c": 1.0},
        "Subtropical Northern Hemisphere": {"a": 0.030, "b": 2.4, "c": 1.0},
        "Subtropical Southern Hemisphere": {"a": 0.035, "b": 2.3, "c": 1.0},
    }

    if aez_identifier in aez_table:
        return aez_table[aez_identifier]

    # 4. Default fallback if both zone and species are missing or unknown (Priority 3)
    return {"a": 0.25, "b": 2.0, "c": 1.0}


# =========================================================
# ----------------- CO2 CALCULATION CORE ------------------
# =========================================================

def calculate_co2_sequestered(dbh_cm=None, height_m=None, rcd_cm=None, species=None, latitude=None, longitude=None):
    """
    Calculate the total CO₂ stock in a tree based on dimensions, species, and AEZ.

    Args:
        dbh_cm (float): Diameter at breast height in centimeters.
        height_m (float): Tree height in meters.
        rcd_cm (float): Root collar diameter in centimeters (used if DBH is not provided).
        species (str, optional): Tree species scientific name.
        latitude (float, optional): Geographic latitude for AEZ lookup.
        longitude (float, optional): Geographic longitude for AEZ lookup.

    Returns:
        float: Total CO₂ stock in the tree in kg.
    """
    # 1. Estimate DBH from RCD if DBH not provided
    if dbh_cm is None and rcd_cm is not None:
        # Approximate conversion factor (may vary by species/location)
        dbh_cm = rcd_cm * 0.8  

    if not isinstance(dbh_cm, (int, float)) or not isinstance(height_m, (int, float)):
        raise ValueError("DBH (or RCD) and height must be numeric values")
    if dbh_cm <= 0 or height_m <= 0:
        return 0.0

    # 2. Determine Agro-Ecological Zone
    aez_identifier = None
    if latitude is not None and longitude is not None:
        try:
            aez_identifier = get_agro_ecological_zone(float(latitude), float(longitude))
        except (TypeError, ValueError):
            pass

    # 3. Get allometric coefficients
    coeffs = get_aez_coefficients(aez_identifier, species)
    a, b, c = coeffs["a"], coeffs["b"], coeffs["c"]

    # 4. Calculate Above Ground Biomass (AGB) using the Allometric Equation
    # AGB (kg) = a * (DBH^b) * (Height^c)
    agb_kg = a * (dbh_cm ** b) * (height_m ** c)
    
    # 5. Convert Biomass to CO₂ Stock
    # Step A: Total Biomass (Above + Below Ground)
    # Assumes a default Root-to-Shoot Ratio (R/S) of 0.2, so Total = AGB * 1.2
    total_biomass = agb_kg * 1.2         
    
    # Step B: Dry Weight
    # Assumes a Dry Matter Content of 72.5% (common average)
    dry_weight = total_biomass * 0.725   
    
    # Step C: Carbon Mass
    # Assumes 50% Carbon Content in Dry Matter
    carbon_kg = dry_weight * 0.5         
    
    # Step D: CO₂ Mass (Stock)
    # Conversion factor from C to CO₂ (Molar Mass Ratio: 44/12 ≈ 3.67)
    co2_kg = carbon_kg * 3.67            

    # The result is the total CO₂ stock in the tree (kg), not the annual sequestration rate.
    return co2_kg
