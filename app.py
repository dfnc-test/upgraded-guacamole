import requests
import pandas as pd
import streamlit as st

LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

STOP_LOSS_PCT = 0.03
TAKE_PROFIT_PCT = 0.05
HIGH_VALUE_THRESHOLD = 1_000_000


@st.cache_data(ttl=60)
def fetch_data():
    try:
        prices_res = requests.get(LATEST_URL, headers=HEADERS, timeout=10)
        volumes_res = requests.get(VOLUME_URL, headers=HEADERS, timeout=10)
        mapping_res = requests.get(MAPPING_URL, headers=HEADERS, timeout=10)

        if prices_res.status_code != 200 or volumes_res.status_code != 200:
            st.error("API request failed")
            return {}, {}, {}

        prices = prices_res.json().get("data", {})
        volumes = volumes_res.json().get("data", {})
        mapping = mapping_res.json()

        id_to_name = {item["id"]: item["name"] for item in mapping}

        return prices, volumes, id_to_name

    except Exception as e:
        st.error(f"API Error: {e}")
        return {}, {}, {}


def analyze_items(prices, volumes, names, capital, mode):
    rows = []

    # ✅ Relaxed filters so results actually show
    if mode == "Safe":
        min_volume = 500
        min_margin = 20
        min_roi = 0.002
        max_fill_time = 4
    else:  # Relaxed
        min_volume = 50
        min_margin = 10
        min_roi = 0.001
        max_fill_time = 12

    for item_id, data in prices.items():
        item_id = int(item_id)

        high = data.get("high")
        low = data.get("low")

        if not high or not low or low == 0:
            continue

        # ✅ FIXED volume
        vol_data = volumes.get(str(item_id), {})
        high_vol = vol_data.get("highPriceVolume", 0)
        low_vol = vol_data.get("lowPriceVolume", 0)
        vol = high_vol + low_vol

        if vol < min_volume:
            continue

        margin = high - low
        roi = margin / low

        if margin < min_margin or roi < min_roi:
            continue

        # ✅ Less aggressive execution penalty
        real_buy = int(low * 1.002)
        real_sell = int(high * 0.998)
        real_margin = real_sell - real_buy

        if real_margin <= 0:
            continue

        real_roi = real_margin / real_buy

        # Fill time estimate
        fills_per_hour = vol / 24
        if fills_per_hour == 0:
            continue

        trade_size = min(capital // real_buy, int(vol * 0.2))
        if trade_size == 0:
            continue

        time_to_fill = trade_size / fills_per_hour

        if time_to_fill > max_fill_time:
            continue

        name = names.get(item_id, "Unknown")

        stop_loss = int(real_buy * (1 - STOP_LOSS_PCT))
        take_profit = int(real_buy * (1 + TAKE_PROFIT_PCT))

        liquidity_score = round((vol / max(time_to_fill, 0.1)) / 1000, 2)

        rows.append({
            "Item": name,
            "Buy": real_buy,
            "Sell": real_sell,
            "Margin": real_margin,
            "ROI %": round(real_roi * 100, 2),
            "Volume": vol,
            "Fill (hrs)": round(time_to_fill, 2),
            "Stop Loss": stop_loss,
            "Take Profit": take_profit,
            "Liquidity": liquidity_score
        })

    df = pd.DataFrame(rows)

    if df.empty:
        return df, df, 0

    df = df.sort_values(by="Liquidity", ascending=False)

    high_value = df[df["Buy"] >= HIGH_VALUE_THRESHOLD]
    normal = df[df["Buy"] < HIGH_VALUE_THRESHOLD]

    return normal.head(15), high_value.head(10), len(df)
