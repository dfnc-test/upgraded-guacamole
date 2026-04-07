import streamlit as st
import requests
import pandas as pd

VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"

HEADERS = {"User-Agent": "GE-Volume-Test"}

@st.cache_data(ttl=60)
def fetch_volume_data():
    volume_data = requests.get(VOLUME_URL, headers=HEADERS, timeout=10).json()["data"]
    mapping = requests.get(MAPPING_URL, headers=HEADERS, timeout=10).json()

    id_to_name = {item["id"]: item["name"] for item in mapping}

    rows = []
    for item_id, data in volume_data.items():
        item_id = int(item_id)
        volume = data.get("volume", 0)

        if volume > 0:
            rows.append({
                "Item": id_to_name.get(item_id, "Unknown"),
                "Volume": volume
            })

    df = pd.DataFrame(rows)
    df = df.sort_values(by="Volume", ascending=False)

    return df.head(10)


st.set_page_config(page_title="OSRS Volume Test")
st.title("📦 Top 10 Most Traded Items (24h)")

top_items = fetch_volume_data()

if top_items.empty:
    st.write("No data returned — API may not be working.")
else:
    st.dataframe(top_items)
