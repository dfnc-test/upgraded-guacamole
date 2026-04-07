import streamlit as st
import requests
import pandas as pd

VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

@st.cache_data(ttl=60)
def fetch_volume_data():
    try:
        vol_res = requests.get(VOLUME_URL, headers=HEADERS, timeout=10)
        map_res = requests.get(MAPPING_URL, headers=HEADERS, timeout=10)

        # ✅ Check status BEFORE parsing JSON
        if vol_res.status_code != 200:
            st.error(f"Volume API failed: {vol_res.status_code}")
            st.text(vol_res.text[:500])
            return pd.DataFrame()

        if map_res.status_code != 200:
            st.error(f"Mapping API failed: {map_res.status_code}")
            st.text(map_res.text[:500])
            return pd.DataFrame()

        # ✅ Safe JSON parsing
        try:
            volume_json = vol_res.json()
            mapping_json = map_res.json()
        except Exception:
            st.error("Failed to decode JSON (likely blocked by API)")
            st.text(vol_res.text[:500])
            return pd.DataFrame()

        volume_data = volume_json.get("data", {})

        if not volume_data:
            st.error("No data returned from API")
            st.write(volume_json)
            return pd.DataFrame()

        id_to_name = {item["id"]: item["name"] for item in mapping_json}

        rows = []
        for item_id, data in volume_data.items():
            item_id = int(item_id)

            high_vol = data.get("highPriceVolume", 0)
            low_vol = data.get("lowPriceVolume", 0)
            volume = high_vol + low_vol

            rows.append({
                "Item": id_to_name.get(item_id, "Unknown"),
                "Volume": volume
            })

        df = pd.DataFrame(rows)

        if df.empty:
            return df

        return df.sort_values(by="Volume", ascending=False).head(10)

    except requests.exceptions.RequestException as e:
        st.error(f"Request failed: {e}")
        return pd.DataFrame()


st.title("📦 Top 10 Most Traded Items (24h)")

top_items = fetch_volume_data()

if top_items.empty:
    st.write("No data returned.")
else:
    st.dataframe(top_items)
