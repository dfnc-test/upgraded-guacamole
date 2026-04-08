import streamlit as st
import requests
import pandas as pd
import numpy as np
import json
import os

# ---------- CONFIG ----------
LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"

HEADERS = {"User-Agent": "osrs-ge-dashboard"}

GE_TAX = 0.05
MIN_VOLUME = 500
WATCHLIST_FILE = "watchlist.json"

# ---------- HELPERS ----------
def get_image_url(name):
    formatted = name.replace(" ", "_").replace("'", "").replace("(", "").replace(")", "")
    return f"https://oldschool.runescape.wiki/images/{formatted}.png"

@st.cache_data(ttl=60)
def fetch_data():
    prices = requests.get(LATEST_URL, headers=HEADERS).json()["data"]
    volumes = requests.get(VOLUME_URL, headers=HEADERS).json()["data"]
    mapping = requests.get(MAPPING_URL, headers=HEADERS).json()

    id_to_name = {item["id"]: item["name"] for item in mapping}
    id_to_limit = {item["id"]: item.get("limit", 0) for item in mapping}

    return prices, volumes, id_to_name, id_to_limit

@st.cache_data(ttl=1800)
def fetch_history(item_id):
    try:
        url = f"https://prices.runescape.wiki/api/v1/osrs/timeseries?id={item_id}&timestep=1h"
        res = requests.get(url, headers=HEADERS).json()
        data = res.get("data", [])

        prices = []
        for point in data:
            high = point.get("avgHighPrice", 0)
            low = point.get("avgLowPrice")

            if high and low:
                prices.append((high + low) / 2)
            elif high:
                prices.append(high)

        if len(prices) < 5:
            return None

        return pd.Series(prices)

    except:
        return None

# ---------- CALCULATIONS ----------
def calculate_flips(prices, volumes, names, limits):
    rows = []

    for item_id, data in prices.items():
        item_id = int(item_id)
        high, low = data.get("high"), data.get("low")

        if not high or not low or low <= 0:
            continue

        volume = volumes.get(str(item_id), {}).get("highPriceVolume", 0) + \
                 volumes.get(str(item_id), {}).get("lowPriceVolume", 0)

        if volume < MIN_VOLUME:
            continue

        real_sell = high * (1 - GE_TAX)
        margin = real_sell - low

        if margin <= 0:
            continue

        roi = margin / low
        spread_pct = (high - low) / low

        buy_limit = limits.get(item_id, 0)
        fills_per_hour = volume / 24 if volume > 0 else 1
        time_to_sell = min(buy_limit / fills_per_hour, 4) if fills_per_hour > 0 else 1
        profit_hour = (margin * buy_limit) / max(time_to_sell, 0.1)

        # ----- HISTORY -----
        hist = fetch_history(item_id)

        z = 0
        momentum = 0

        if hist is not None:
            mean = hist.mean()
            std = hist.std(ddof=0)
            if std > 0:
                z = (hist.iloc[-1] - mean) / std

            if len(hist) >= 4:
                momentum = (hist.iloc[-1] - hist.iloc[-4]) / hist.iloc[-4]

        # ----- SMART SCORE -----
        score = 0

        if z < -0.5:
            score += 25
        elif z < -0.2:
            score += 10

        if momentum > 0:
            score += 20
        elif momentum < 0:
            score -= 10

        score += min(volume / 100_000, 1) * 20
        score += min(spread_pct / 0.05, 1) * 20
        score += min(roi / 0.1, 1) * 15

        # ----- SIGNAL -----
        if score > 70:
            signal = "STRONG BUY"
        elif score > 50:
            signal = "BUY"
        elif score < 30:
            signal = "SELL"
        else:
            signal = "HOLD"

        rows.append({
            "Image": get_image_url(names.get(item_id, "Unknown")),
            "Item": names.get(item_id, "Unknown"),
            "Buy": int(low),
            "Sell": int(real_sell),
            "Margin": int(margin),
            "ROI %": round(roi * 100, 2),
            "Spread %": round(spread_pct * 100, 2),
            "Volume": volume,
            "Profit/Hr": int(profit_hour),
            "Score": round(score, 1),
            "Z": round(z, 2),
            "Momentum %": round(momentum * 100, 2),
            "Signal": signal
        })

    return pd.DataFrame(rows).sort_values(by="Profit/Hr", ascending=False)

# ---------- DISPLAY ----------
def render_table(df, key):
    headers = ["Img","Item","Buy","Sell","Margin","ROI","Spread","Vol","P/H","Score","Z","Mom","Signal","+"]
    widths = [0.5,2,1,1,1,1,1,1,1,1,1,1,1,0.4]

    cols = st.columns(widths)
    for c,h in zip(cols, headers):
        c.markdown(f"**{h}**")

    for i,row in df.head(20).iterrows():
        cols = st.columns(widths)

        cols[0].markdown(f'<img src="{row["Image"]}" width="25">', unsafe_allow_html=True)
        cols[1].markdown(f"**{row['Item']}**")
        cols[2].markdown(row["Buy"])
        cols[3].markdown(row["Sell"])
        cols[4].markdown(row["Margin"])
        cols[5].markdown(row["ROI %"])
        cols[6].markdown(row["Spread %"])
        cols[7].markdown(row["Volume"])
        cols[8].markdown(row["Profit/Hr"])
        cols[9].markdown(row["Score"])
        cols[10].markdown(row["Z"])
        cols[11].markdown(row["Momentum %"])

        color = "green" if "BUY" in row["Signal"] else "red" if row["Signal"] == "SELL" else "gray"
        cols[12].markdown(f"<span style='color:{color}'>{row['Signal']}</span>", unsafe_allow_html=True)

        if cols[13].button("+", key=f"{key}_{i}"):
            if "watchlist" not in st.session_state:
                st.session_state.watchlist = []

            st.session_state.watchlist.append(row.to_dict())

# ---------- MAIN ----------
st.set_page_config(layout="wide")
st.title("📊 OSRS GE Smart Flipping Dashboard")

prices, volumes, names, limits = fetch_data()
df = calculate_flips(prices, volumes, names, limits)

# ---------- TABLES ----------

st.subheader("⚡ High Volume Scalp")
render_table(df[df["Volume"] > 100000], "scalp")

st.subheader("💰 Standard Flips")
render_table(df[(df["Volume"] > 10000) & (df["Margin"] > 20)], "standard")

st.subheader("🎯 Mispriced Opportunities")
render_table(df[df["Z"] < -0.4], "opportunity")

st.subheader("🚀 Momentum Trades")
render_table(df[df["Momentum %"] > 3], "momentum")
