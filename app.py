import streamlit as st
import requests
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime

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

def save_watchlist(watchlist):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(watchlist, f)

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, "r") as f:
                return json.load(f)
        except:
            return []
    return []

# ---------- DATA ----------
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

        hist = fetch_history(item_id)
        z, momentum = 0, 0

        if hist is not None:
            std = hist.std(ddof=0)
            if std > 0:
                z = (hist.iloc[-1] - hist.mean()) / std
            if len(hist) >= 4:
                momentum = (hist.iloc[-1] - hist.iloc[-4]) / hist.iloc[-4]

        # ----- Liquidity Model -----
        fills_per_hour = volume / 24 if volume > 0 else 1
        safe_qty = int(fills_per_hour * 2 * 0.3)
        recommended_qty = min(buy_limit, safe_qty)

        if recommended_qty < 5:
            continue

        # ----- Filters -----
        min_safe_margin = max(20, low * 0.002)
        if margin < min_safe_margin:
            continue

        if volume < 10000 and spread_pct < 0.03:
            continue

        # ----- Profit -----
        time_to_sell = max(recommended_qty / fills_per_hour, 0.1)
        profit_hour = (margin * recommended_qty) / time_to_sell

        # ----- Dump Risk -----
        liquidity_ratio = volume / max(buy_limit, 1)
        dump_risk = 0
        if liquidity_ratio < 5:
            dump_risk += 40
        elif liquidity_ratio < 10:
            dump_risk += 20
        if spread_pct < 0.01:
            dump_risk += 30
        if momentum < 0:
            dump_risk += 20

        rows.append({
            "Item": names.get(item_id, "Unknown"),
            "Image": get_image_url(names.get(item_id, "Unknown")),
            "Buy": int(low),
            "Sell": int(real_sell),
            "Margin": int(margin),
            "Volume": volume,
            "Spread %": round(spread_pct * 100, 2),
            "Safe Qty": recommended_qty,
            "Profit/Hr": int(profit_hour),
            "Dump Risk": dump_risk,
            "Score": round(profit_hour / max(dump_risk,1),2)  # efficiency
        })

    return pd.DataFrame(rows).sort_values(by="Score", ascending=False)

# ---------- PORTFOLIO OPTIMIZER ----------
def optimize_portfolio(df, gp):
    scalp_pool = gp * 0.6
    margin_pool = gp * 0.4

    portfolio = []

    for _, row in df.iterrows():
        if row["Risk"] == "RISKY":
            continue

        pool = scalp_pool if row["Type"] == "SCALP" else margin_pool

        buy_price = row["Buy"]
        sell_price = row["Sell"]

        qty = min(row["Safe Qty"], int(pool / buy_price))

        if qty <= 0:
            continue

        cost = qty * buy_price
        profit = qty * row["Margin"]

        portfolio.append({
            "Item": row["Item"],
            "Type": row["Type"],
            "Qty": qty,

            # 👇 NEW (this is what you wanted)
            "Buy Price": buy_price,
            "Sell Price": sell_price,

            "Cost": int(cost),
            "Profit": int(profit)
        })

        if row["Type"] == "SCALP":
            scalp_pool -= cost
        else:
            margin_pool -= cost

    return pd.DataFrame(portfolio)
# ---------- WATCHLIST ----------
def render_watchlist():
    st.sidebar.header("👁️ Watchlist")

    if "watchlist" not in st.session_state:
        st.session_state.watchlist = load_watchlist()

    wl = st.session_state.watchlist

    for i, row in enumerate(wl):
        st.sidebar.markdown(f"""
        <div style="border:1px solid #aaa; padding:6px; margin-bottom:6px;">
            <img src="{row['Image']}" width="25">
            <b>{row['Item']}</b><br>
            Buy: {row['Buy']} | Sell: {row['Sell']}
        </div>
        """, unsafe_allow_html=True)

        if st.sidebar.button("❌", key=f"rm_{i}"):
            wl.pop(i)
            save_watchlist(wl)
            st.rerun()

# ---------- MAIN ----------
st.set_page_config(layout="wide")
st.title("📊 OSRS GE Smart Flipping Dashboard")

# Refresh
if st.button("🔄 Refresh Prices"):
    st.cache_data.clear()
    st.rerun()

st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")

# GP Input
gp = st.number_input("💰 Your GP", value=10_000_000, step=1_000_000)

prices, volumes, names, limits = fetch_data()
df = calculate_flips(prices, volumes, names, limits)

# Portfolio
st.subheader("🧠 Optimized Portfolio")
portfolio, remaining = optimize_portfolio(df, gp)
st.dataframe(portfolio)
st.write(f"Remaining GP: {remaining:,}")

# Trades
st.subheader("📈 Best Trades")
st.dataframe(df.head(20))

render_watchlist()
