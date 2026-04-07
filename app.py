import streamlit as st
import requests
import pandas as pd

# ================= CONFIG =================
LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"

HEADERS = {"User-Agent": "GE-Trading-Dashboard"}

STOP_LOSS_PCT = 0.03
TAKE_PROFIT_PCT = 0.05

HIGH_VALUE_THRESHOLD = 1_000_000
# ==========================================

@st.cache_data(ttl=60)
def fetch_data():
    prices = requests.get(LATEST_URL, headers=HEADERS, timeout=5).json()["data"]
    volumes = requests.get(VOLUME_URL, headers=HEADERS, timeout=5).json()["data"]
    mapping = requests.get(MAPPING_URL, headers=HEADERS, timeout=5).json()
    id_to_name = {item["id"]: item["name"] for item in mapping}
    return prices, volumes, id_to_name

def analyze_items(prices, volumes, names, capital, mode):
    rows = []

    # Mode-based filters
    if mode == "Safe":
        min_volume = 1000
        min_margin = 50
        min_roi = 0.005
        max_real_roi = 0.08
        max_fill_time = 2
    else:
        min_volume = 100
        min_margin = 20
        min_roi = 0.002
        max_real_roi = 0.15
        max_fill_time = 6

    for item_id, data in prices.items():
        item_id = int(item_id)
        high = data.get("high")
        low = data.get("low")
        vol_data = volumes.get(str(item_id), {})
        vol = vol_data.get("volume", 0) or vol_data.get("high", 0)

        if not high or not low or low == 0:
            continue
        if vol < min_volume:
            continue

        margin = high - low
        roi = margin / low
        if margin < min_margin or roi < min_roi:
            continue

        real_buy = int(low * 1.01)
        real_sell = int(high * 0.99 * 0.985)  # Tax included
        real_margin = real_sell - real_buy
        if real_margin <= 0:
            continue
        real_roi = real_margin / real_buy
        if real_roi > max_real_roi:
            continue

        fills_per_hour = vol / 24
        if fills_per_hour == 0:
            continue
        trade_size = min(capital // real_buy, int(vol * 0.1))
        if trade_size == 0:
            continue
        time_to_fill = trade_size / fills_per_hour
        if time_to_fill > max_fill_time:
            continue

        stop_loss = int(real_buy * (1 - STOP_LOSS_PCT))
        take_profit = int(real_buy * (1 + TAKE_PROFIT_PCT))
        liquidity_score = round((vol / max(time_to_fill, 0.1)) / 1000, 2)
        buy_limit = vol // 6  # approximate 4-hour buy limit
        profit_per_hour = round(real_margin * fills_per_hour, 2)
        profit_per_limit = round(real_margin * buy_limit, 2)
        confidence = round((vol / 1000) * real_roi * real_margin, 2)

        rows.append({
            "Item": names.get(item_id, "Unknown"),
            "Buy": real_buy,
            "Sell": real_sell,
            "Margin": real_margin,
            "ROI %": round(real_roi*100,2),
            "Volume": vol,
            "Buy Limit": buy_limit,
            "Profit per Limit": profit_per_limit,
            "Profit per Hour": profit_per_hour,
            "Confidence": confidence,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df, df, df, 0

    df = df.sort_values(by="Confidence", ascending=False)
    normal = df[df["Buy"] < HIGH_VALUE_THRESHOLD].head(15)
    high_value = df[df["Buy"] >= HIGH_VALUE_THRESHOLD].head(10)
    speculative = df.sample(min(10, len(df)))  # simplified speculative placeholder
    return normal, high_value, speculative, len(df)

# ---------- UI ----------
st.set_page_config(page_title="OSRS GE Dashboard", layout="centered")
st.title("📊 OSRS GE Trading Dashboard")

mode = st.selectbox("Mode", ["Relaxed", "Safe"])
capital = st.number_input("Available GP", value=10_000_000, step=1_000_000)

prices, volumes, names = fetch_data()
normal, high_value, speculative, total_found = analyze_items(prices, volumes, names, capital, mode)

st.write(f"🔍 Total viable trades found: {total_found}")

# --------- Display tables with sorting ----------
st.subheader("🟢 Profitable Flips")
if normal.empty:
    st.write("No trades found.")
else:
    st.dataframe(normal, use_container_width=True)

st.subheader("🔵 High Value Trades")
if high_value.empty:
    st.write("No high-value trades currently.")
else:
    st.dataframe(high_value, use_container_width=True)

st.subheader("🟠 Speculative / Underpriced Trades")
if speculative.empty:
    st.write("No speculative trades currently.")
else:
    st.dataframe(speculative, use_container_width=True)
