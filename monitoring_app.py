import streamlit as st
from carbonfao import calculate_co2_sequestered, get_ecological_zone, get_zone_coefficients

st.title("CarbonTally Tree Monitoring")

# --- Input Fields ---
dbh = st.number_input("Diameter at Breast Height (cm)", min_value=0.0, step=0.1)
height = st.number_input("Tree Height (m)", min_value=0.0, step=0.1)
species = st.text_input("Species (optional)")
latitude = st.number_input("Latitude", format="%.6f")
longitude = st.number_input("Longitude", format="%.6f")

# --- Automatic Calculation & Breakdown ---
try:
    if dbh > 0 and height > 0:
        co2 = calculate_co2_sequestered(
            dbh_cm=dbh,
            height_m=height,
            species=species,
            latitude=latitude,
            longitude=longitude
        )

        # Determine ecological zone
        zone = get_ecological_zone(latitude, longitude)
        coeffs = get_zone_coefficients(zone, species)
        a, b, c = coeffs["a"], coeffs["b"], coeffs["c"]

        # Step-by-step calculation
        agb = a * (dbh ** b) * (height ** c)
        total_biomass = agb * 1.2
        dry_weight = total_biomass * 0.725
        carbon = dry_weight * 0.5
        co2_check = carbon * 3.67

        # --- Display breakdown ---
        st.subheader("CO₂ Calculation Breakdown for This Tree")
        st.write(f"- **DBH:** {dbh:.2f} cm")
        st.write(f"- **Height:** {height:.2f} m")
        st.write(f"- **Species:** {species or 'Unknown'}")
        st.write(f"- **Ecological Zone:** {zone or 'Unknown'}")
        st.write(f"- **Coefficients used:** a = {a}, b = {b}, c = {c}")
        st.write(f"- **Above-Ground Biomass (AGB):** {agb:.2f} kg")
        st.write(f"- **Total Biomass (AGB × 1.2):** {total_biomass:.2f} kg")
        st.write(f"- **Dry Weight (Total Biomass × 0.725):** {dry_weight:.2f} kg")
        st.write(f"- **Carbon Content (Dry Weight × 0.5):** {carbon:.2f} kg")
        st.success(f"**CO₂ Sequestered:** {co2_check:.2f} kg")

except Exception as e:
    st.error(f"Error in calculation: {e}")
