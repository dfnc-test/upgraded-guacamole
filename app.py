import streamlit as st
import requests
import pandas as pd
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

def save_watchlist(wl):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(wl, f)

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        try:
            return json.load(open(WATCHLIST_FILE))
        except:
            return []
    return []

# ---------- DATA ----------
@st.cache_data(ttl=60)
def fetch_data():
    prices = requests.get(LATEST_URL, headers=HEADERS).json()["data"]
    volumes = requests.get(VOLUME_URL, headers=HEADERS).json()["data"]
    mapping = requests.get(MAPPING_URL, headers=HEADERS).json()

    names = {i["id"]: i["name"] for i in mapping}
    limits = {i["id"]: i.get("limit", 0) for i in mapping}

    return prices, volumes, names, limits

@st.cache_data(ttl=1800)
def fetch_history(item_id):
    try:
        url = f"https://prices.runescape.wiki/api/v1/osrs/timeseries?id={item_id}&timestep=1h"
        data = requests.get(url, headers=HEADERS).json().get("data", [])

        prices = []
        for p in data:
            h, l = p.get("avgHighPrice"), p.get("avgLowPrice")
            if h and l:
                prices.append((h + l) / 2)
            elif h:
                prices.append(h)

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

        spread_pct = (high - low) / low
        buy_limit = limits.get(item_id, 0)

        hist = fetch_history(item_id)
        momentum = 0

        if hist is not None and len(hist) >= 4:
            momentum = (hist.iloc[-1] - hist.iloc[-4]) / hist.iloc[-4]

        # ----- Liquidity -----
        fills_per_hour = volume / 24 if volume > 0 else 1
        safe_qty = int(fills_per_hour * 2 * 0.3)
        safe_qty = min(buy_limit, safe_qty)

        if safe_qty < 5:
            continue

        # ----- Filters -----
        if volume < 10000 and spread_pct < 0.03:
            continue

        # ----- Profit -----
        time_to_sell = max(safe_qty / fills_per_hour, 0.1)
        profit_hour = (margin * safe_qty) / time_to_sell

        # ----- Risk -----
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

        if dump_risk < 30:
            risk = "SAFE"
        elif dump_risk < 60:
            risk = "MEDIUM"
        else:
            risk = "RISKY"

        # ----- Margin Lifetime -----
        base = 120

        if volume > 200000:
            base *= 0.4
        elif volume > 100000:
            base *= 0.6

        if spread_pct < 0.01:
            base *= 0.4
        elif spread_pct < 0.02:
            base *= 0.6

        if momentum < -0.03:
            base *= 0.5
        elif momentum < -0.01:
            base *= 0.7
        elif momentum > 0.02:
            base *= 1.2

        margin_time = int(max(5, min(base, 240)))

        if margin_time < 15:
            window = "⚡ VERY FAST"
        elif margin_time < 45:
            window = "⏱️ FAST"
        elif margin_time < 120:
            window = "🕐 MEDIUM"
        else:
            window = "🐢 SLOW"

        # ----- Type -----
        if volume > 100000:
            ttype = "SCALP"
        elif spread_pct > 0.05:
            ttype = "HIGH MARGIN"
        else:
            ttype = "STANDARD"

        rows.append({
            "Item": names.get(item_id, "Unknown"),
            "Buy": int(low),
            "Sell": int(real_sell),
            "Margin": int(margin),
            "Volume": volume,
            "Safe Qty": safe_qty,
            "Profit/Hr": int(profit_hour),
            "Risk": risk,
            "Time": margin_time,
            "Window": window,
            "Type": ttype,
            "Image": get_image_url(names.get(item_id, "Unknown"))
        })

    return pd.DataFrame(rows).sort_values(by="Profit/Hr", ascending=False)

# ---------- PORTFOLIO ----------
def optimize_portfolio(df, gp):
    if "Risk" not in df.columns:
        df["Risk"] = "SAFE"

    scalp_pool = gp * 0.6
    margin_pool = gp * 0.4

    portfolio = []

    for _, row in df.iterrows():
        if row["Risk"] == "RISKY":
            continue
        if row["Time"] < 15:
            continue

        pool = scalp_pool if row["Type"] == "SCALP" else margin_pool

        qty = min(row["Safe Qty"], int(pool / row["Buy"]))
        if qty <= 0:
            continue

        portfolio.append({
            "Item": row["Item"],
            "Type": row["Type"],
            "Qty": qty,
            "Buy Price": row["Buy"],
            "Sell Price": row["Sell"],
            "Profit/Unit": row["Margin"],
            "Total Profit": int(qty * row["Margin"])
        })

        if row["Type"] == "SCALP":
            scalp_pool -= qty * row["Buy"]
        else:
            margin_pool -= qty * row["Buy"]

    return pd.DataFrame(portfolio)

# ---------- WATCHLIST ----------
def render_watchlist():
    st.sidebar.header("👁️ Watchlist")

    if "watchlist" not in st.session_state:
        st.session_state.watchlist = load_watchlist()

    for i, row in enumerate(st.session_state.watchlist):
        st.sidebar.markdown(f"""
        <div style="border:1px solid #aaa; padding:6px; margin-bottom:6px;">
        <img src="{row['Image']}" width="25">
        <b>{row['Item']}</b><br>
        Buy: {row['Buy']} | Sell: {row['Sell']}
        </div>
        """, unsafe_allow_html=True)

        if st.sidebar.button("❌", key=f"rm_{i}"):
            st.session_state.watchlist.pop(i)
            save_watchlist(st.session_state.watchlist)
            st.rerun()

# ---------- MAIN ----------
st.set_page_config(layout="wide")
st.title("📊 OSRS GE Pro Flipping Dashboard")

if st.button("🔄 Refresh Prices"):
    st.cache_data.clear()
    st.rerun()

st.caption(f"Updated: {datetime.now().strftime('%H:%M:%S')}")

gp = st.number_input("💰 Your GP", value=10_000_000, step=1_000_000)

prices, volumes, names, limits = fetch_data()
df = calculate_flips(prices, volumes, names, limits)

st.subheader("🧠 Optimized Portfolio")
st.dataframe(optimize_portfolio(df, gp))

st.subheader("📈 Trade Opportunities")
st.dataframe(df.head(30))

render_watchlist()
