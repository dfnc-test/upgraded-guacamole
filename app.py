import streamlit as st
import requests
import pandas as pd

LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"

# ✅ IMPORTANT: Use a REAL identifiable agent
HEADERS = {
    "User-Agent": "osrs-ge-dashboard (redsnow360@gmail.com)"
}

@st.cache_data(ttl=60)
def fetch_data():
    try:
        prices_res = requests.get(LATEST_URL, headers=HEADERS, timeout=10)
        volumes_res = requests.get(VOLUME_URL, headers=HEADERS, timeout=10)
        mapping_res = requests.get(MAPPING_URL, headers=HEADERS, timeout=10)

        st.write("Status:", prices_res.status_code, volumes_res.status_code)

        if prices_res.status_code != 200:
            st.error("Price API blocked")
            st.text(prices_res.text[:300])
            return {}, {}, {}

        if volumes_res.status_code != 200:
            st.error("Volume API blocked")
            st.text(volumes_res.text[:300])
            return {}, {}, {}

        prices = prices_res.json().get("data", {})
        volumes = volumes_res.json().get("data", {})
        mapping = mapping_res.json()

        id_to_name = {item["id"]: item["name"] for item in mapping}

        return prices, volumes, id_to_name

    except Exception as e:
        st.error(f"Fetch error: {e}")
        return {}, {}, {}


def analyze_items(prices, volumes, names):
    rows = []

    for item_id, data in prices.items():
        item_id = int(item_id)

        high = data.get("high")
        low = data.get("low")

        if not high or not low:
            continue

        vol_data = volumes.get(str(item_id), {})
        volume = (
            vol_data.get("highPriceVolume", 0) +
            vol_data.get("lowPriceVolume", 0)
        )

        if volume <= 0:
            continue

        rows.append({
            "Item": names.get(item_id, "Unknown"),
            "Buy": low,
            "Sell": high,
            "Margin": high - low,
            "Volume": volume
        })

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    return df.sort_values(by="Volume", ascending=False).head(20)


st.title("📊 OSRS GE Dashboard")

prices, volumes, names = fetch_data()

if prices and volumes:
    df = analyze_items(prices, volumes, names)

    if df.empty:
        st.warning("No items found")
    else:
        st.dataframe(df)
else:
    st.error("API is blocked (403). Fix User-Agent.")
