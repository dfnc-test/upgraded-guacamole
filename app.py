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
GE_TAX = 0.05  # 5% Grand Exchange tax
BUY_LIMIT_HOURS = 4  # Time window for buy limit calculations

# ---------- FETCH ----------
@st.cache_data(ttl=60)
def fetch_data():
    prices_res = requests.get(LATEST_URL, headers=HEADERS, timeout=10)
    volumes_res = requests.get(VOLUME_URL, headers=HEADERS, timeout=10)
    mapping_res = requests.get(MAPPING_URL, headers=HEADERS, timeout=10)

    prices = prices_res.json()["data"]
    volumes = volumes_res.json()["data"]
    mapping = mapping_res.json()

    id_to_name = {item["id"]: item["name"] for item in mapping}

    return prices, volumes, id_to_name

# ---------- ANALYZE ----------
def analyze_items(prices, volumes, names):
    rows = []

    for item_id, data in prices.items():
        item_id = int(item_id)

        high = data.get("high")
        low = data.get("low")
        buy_limit = data.get("limit", 0)  # daily buy limit

        if not high or not low or low <= 0:
            continue

        vol_data = volumes.get(str(item_id), {})
        volume = (
            vol_data.get("highPriceVolume", 0) +
            vol_data.get("lowPriceVolume", 0)
        )

        if volume < MIN_VOLUME:
            continue

        # Apply GE tax
        real_sell = high * (1 - GE_TAX)
        real_margin = real_sell - low

        if real_margin < MIN_MARGIN:
            continue

        roi = real_margin / low

        # Profit per buy limit (assume buy limit resets every 4 hours)
        profit_per_limit = real_margin * buy_limit

        # Estimate time to sell based on 24h volume
        fills_per_hour = volume / 24
        time_to_sell_hours = min(buy_limit / fills_per_hour, BUY_LIMIT_HOURS) if fills_per_hour > 0 else 0.1

        profit_per_hour = profit_per_limit / max(time_to_sell_hours, 0.1)

        rows.append({
            "Item": names.get(item_id, "Unknown"),
            "Buy": low,
            "Sell": int(real_sell),
            "Margin": int(real_margin),
            "ROI %": round(roi * 100, 2),
            "Volume": volume,
            "Buy Limit": buy_limit,
            "Profit per Limit": int(profit_per_limit),
            "Profit per Hour": int(profit_per_hour)
        })

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    # Rank by most profitable per hour
    df = df.sort_values(by="Profit per Hour", ascending=False)
    return df.head(20)

# ---------- UI ----------
st.set_page_config(page_title="OSRS GE Dashboard", layout="centered")
st.title("📊 OSRS GE Trading Dashboard with Profit/Hour")

prices, volumes, names = fetch_data()
df = analyze_items(prices, volumes, names)

if df.empty:
    st.warning("No trades found — try lowering filters or increasing min volume")
else:
    st.dataframe(df)
