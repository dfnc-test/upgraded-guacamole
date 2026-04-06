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


# ---------- Helpers ----------
def get_image_url(name):
    formatted = (
        name.replace(" ", "_")
        .replace("'", "")
        .replace("(", "")
        .replace(")", "")
    )
    return f"https://oldschool.runescape.wiki/images/{formatted}.png"


@st.cache_data(ttl=60)
def fetch_data():
    prices = requests.get(LATEST_URL, headers=HEADERS, timeout=5).json()["data"]
    volumes = requests.get(VOLUME_URL, headers=HEADERS, timeout=5).json()["data"]
    mapping = requests.get(MAPPING_URL, headers=HEADERS, timeout=5).json()

    id_to_name = {item["id"]: item["name"] for item in mapping}

    return prices, volumes, id_to_name


def analyze_items(prices, volumes, names, capital, mode):
    rows = []

    # 🔁 Mode-based filters
    if mode == "Safe":
        min_volume = 1000
        min_margin = 50
        min_roi = 0.005
        max_real_roi = 0.08
        max_fill_time = 2
    else:  # Relaxed
        min_volume = 100
        min_margin = 20
        min_roi = 0.002
        max_real_roi = 0.15
        max_fill_time = 6

    for item_id, data in prices.items():
        item_id = int(item_id)

        high = data.get("high")
        low = data.get("low")

        # ✅ FIXED volume handling
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

        # Simulate realistic execution
        real_buy = int(low * 1.01)
        real_sell = int(high * 0.99)
        real_margin = real_sell - real_buy

        if real_margin <= 0:
            continue

        real_roi = real_margin / real_buy

        if real_roi > max_real_roi:
            continue

        # Fill-time estimate
        fills_per_hour = vol / 24
        if fills_per_hour == 0:
            continue

        trade_size = min(capital // real_buy, int(vol * 0.1))
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
            "Liquidity": liquidity_score,
            "Image": get_image_url(name)
        })

    df = pd.DataFrame(rows)

    if df.empty:
        return df, df, 0

    df = df.sort_values(by="Liquidity", ascending=False)

    high_value = df[df["Buy"] >= HIGH_VALUE_THRESHOLD]
    normal = df[df["Buy"] < HIGH_VALUE_THRESHOLD]

    return normal.head(15), high_value.head(10), len(df)


# ---------- UI ----------
st.set_page_config(page_title="OSRS GE Dashboard", layout="centered")
st.title("📊 OSRS GE Trading Dashboard")

# Mode toggle
mode = st.selectbox("Mode", ["Relaxed", "Safe"])

capital = st.number_input("Available GP", value=10_000_000, step=1_000_000)

prices, volumes, names = fetch_data()
normal, high_value, total_found = analyze_items(prices, volumes, names, capital, mode)

# Debug info
st.write(f"🔍 Total viable trades found: {total_found}")

# --------- Display ----------
st.subheader("🟢 High Liquidity Flips")

if normal.empty:
    st.write("No trades found. Try Relaxed mode or increasing capital.")
else:
    for _, row in normal.iterrows():
        cols = st.columns([1, 3])

        with cols[0]:
            st.image(row["Image"], width=50)

        with cols[1]:
            st.markdown(f"**{row['Item']}**")
            st.write(f"Buy: {row['Buy']} | Sell: {row['Sell']} | Margin: {row['Margin']} gp")
            st.write(f"ROI: {row['ROI %']}% | Volume: {row['Volume']}")
            st.write(f"Fill: {row['Fill (hrs)']}h | Liquidity: {row['Liquidity']}")
            st.write(f"SL: {row['Stop Loss']} | TP: {row['Take Profit']}")

st.subheader("🔵 High Value Trades")

if high_value.empty:
    st.write("No high-value trades currently.")
else:
    for _, row in high_value.iterrows():
        cols = st.columns([1, 3])

        with cols[0]:
            st.image(row["Image"], width=50)

        with cols[1]:
            st.markdown(f"**{row['Item']}**")
            st.write(f"Buy: {row['Buy']} | Sell: {row['Sell']} | Margin: {row['Margin']} gp")
            st.write(f"ROI: {row['ROI %']}% | Volume: {row['Volume']}")
            st.write(f"Fill: {row['Fill (hrs)']}h | Liquidity: {row['Liquidity']}")
