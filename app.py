import streamlit as st
import requests
import pandas as pd

# ---------- CONFIG ----------
LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"

HEADERS = {
    "User-Agent": "osrs-ge-dashboard (youremail@gmail.com)"
}

MIN_VOLUME = 1000
MIN_MARGIN = 20

# ---------- FETCH ----------
@st.cache_data(ttl=60)
def fetch_data():
    prices = requests.get(LATEST_URL, headers=HEADERS, timeout=10).json()["data"]
    volumes = requests.get(VOLUME_URL, headers=HEADERS, timeout=10).json()["data"]
    mapping = requests.get(MAPPING_URL, headers=HEADERS, timeout=10).json()

    id_to_name = {item["id"]: item["name"] for item in mapping}

    return prices, volumes, id_to_name


# ---------- ANALYZE ----------
def analyze_items(prices, volumes, names):
    rows = []

    for item_id, data in prices.items():
        item_id = int(item_id)

        high = data.get("high")
        low = data.get("low")

        if not high or not low or low <= 0:
            continue

        vol_data = volumes.get(str(item_id), {})
        volume = (
            vol_data.get("highPriceVolume", 0) +
            vol_data.get("lowPriceVolume", 0)
        )

        if volume < MIN_VOLUME:
            continue

        margin = high - low

        if margin < MIN_MARGIN:
            continue

        roi = margin / low

        rows.append({
            "Item": names.get(item_id, "Unknown"),
            "Buy": low,
            "Sell": high,
            "Margin": margin,
            "ROI %": round(roi * 100, 2),
            "Volume": volume
        })

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    # ✅ Sort by best opportunities
    df["Score"] = df["Margin"] * df["Volume"]
    df = df.sort_values(by="Score", ascending=False)

    return df.head(20)


# ---------- UI ----------
st.set_page_config(page_title="OSRS GE Dashboard", layout="centered")
st.title("📊 OSRS GE Trading Dashboard")

prices, volumes, names = fetch_data()
df = analyze_items(prices, volumes, names)

if df.empty:
    st.warning("No trades found — try lowering filters")
else:
    st.dataframe(df)
