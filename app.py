import streamlit as st
import requests
import pandas as pd

VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"

HEADERS = {"User-Agent": "GE-Volume-Test"}

@st.cache_data(ttl=60)
def fetch_volume_data():
    vol_response = requests.get(VOLUME_URL, headers=HEADERS, timeout=10)
    map_response = requests.get(MAPPING_URL, headers=HEADERS, timeout=10)

    # 🔍 Debug raw responses
    st.write("Status codes:", vol_response.status_code, map_response.status_code)

    try:
        volume_json = vol_response.json()
        mapping_json = map_response.json()
    except Exception as e:
        st.error(f"JSON decode failed: {e}")
        return pd.DataFrame()

    st.write("Volume JSON sample:", list(volume_json.keys()))

    volume_data = volume_json.get("data", {})
    if not volume_data:
        st.error("No 'data' field in volume response")
        st.write(volume_json)
        return pd.DataFrame()

    id_to_name = {item["id"]: item["name"] for item in mapping_json}

    rows = []
    for item_id, data in volume_data.items():
        item_id = int(item_id)
        volume = data.get("volume", 0)

        rows.append({
            "Item": id_to_name.get(item_id, "Unknown"),
            "Volume": volume
        })

    df = pd.DataFrame(rows)

    # ✅ Prevent crash if empty
    if df.empty or "Volume" not in df.columns:
        st.error("DataFrame is empty or malformed")
        st.write(df)
        return df

    df = df.sort_values(by="Volume", ascending=False)
    return df.head(10)


st.title("📦 Volume Debug")

top_items = fetch_volume_data()

if not top_items.empty:
    st.dataframe(top_items)
