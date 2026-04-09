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

# ---------- ANALYZER ----------
def analyze_item(item_name, prices, volumes, names, limits):
    item_id = None
    for k, v in names.items():
        if v.lower() == item_name.lower():
            item_id = k
            break

    if item_id is None:
        return None

    item_id = int(item_id)
    data = prices.get(str(item_id))
    if not data:
        return None

    high, low = data.get("high"), data.get("low")
    volume = volumes.get(str(item_id), {}).get("highPriceVolume", 0) + \
             volumes.get(str(item_id), {}).get("lowPriceVolume", 0)

    hist = fetch_history(item_id)
    if hist is None or len(hist) < 10:
        return None

    short_momentum = (hist.iloc[-1] - hist.iloc[-3]) / hist.iloc[-3]
    medium_momentum = (hist.iloc[-1] - hist.iloc[-8]) / hist.iloc[-8]
    volatility = hist.pct_change().std()

    real_sell = high * (1 - GE_TAX)
    margin = real_sell - low
    spread_pct = (high - low) / low

    sentiment = sum([
        20 if short_momentum > 0 else 0,
        20 if medium_momentum > 0 else 0,
        20 if spread_pct > 0.03 else 0,
        20 if volume > 50000 else 0,
        20 if volatility < 0.02 else 0
    ])

    entry = int(low * 1.01)
    exit = int(real_sell * 0.99)

    hold = max(2, min(72, int(10 / max(volume/24,1))))

    score = min(100, (
        (margin > 0)*30 +
        (spread_pct > 0.03)*20 +
        (sentiment > 60)*20 +
        (volume > 20000)*15 +
        (volatility < 0.03)*15
    ))

    return {
        "Item": item_name,
        "Entry": entry,
        "Exit": exit,
        "Margin": int(margin),
        "Hold": hold,
        "Score": score,
        "Sentiment": sentiment,
        "Recommendation": "🔥 Strong Flip" if score > 70 else "⚠️ Risky"
    }

# ---------- CALCULATIONS ----------
def calculate_flips(prices, volumes, names, limits, profit_mode=False):
    rows = []

    for item_id, data in prices.items():
        item_id = int(item_id)
        high, low = data.get("high"), data.get("low")

        if not high or not low:
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

        # 🔥 PROFIT MODE ADJUSTMENTS
        if profit_mode:
            if spread_pct < 0.04:
                continue
            if momentum < 0:
                continue
        else:
            if volume < 10000 and spread_pct < 0.03:
                continue

        fills_per_hour = volume / 24 if volume > 0 else 1
        safe_qty = int(min(buy_limit, fills_per_hour * (4 if profit_mode else 2) * 0.5))

        if safe_qty < 5:
            continue

        time_to_sell = max(safe_qty / fills_per_hour, 0.1)

        # 🔥 LONGER HOLD = MORE PROFIT
        if profit_mode:
            time_to_sell *= 2

        profit_hour = (margin * safe_qty) / time_to_sell

        # Risk
        risk_score = 0
        if momentum < 0:
            risk_score += 30
        if spread_pct < 0.02:
            risk_score += 30

        risk = "SAFE" if risk_score < 30 else "MEDIUM" if risk_score < 60 else "RISKY"

        # Window
        margin_time = int(time_to_sell * 60)
        window = "🐢 SLOW" if margin_time > 60 else "⏱️ MEDIUM" if margin_time > 20 else "⚡ FAST"

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
            "Type": "HIGH PROFIT" if profit_mode else "STANDARD",
            "Image": get_image_url(names.get(item_id, "Unknown"))
        })

    return pd.DataFrame(rows).sort_values(by="Profit/Hr", ascending=False)

# ---------- PORTFOLIO ----------
def optimize_portfolio(df, gp):
    portfolio = []

    for _, row in df.iterrows():
        if row["Risk"] == "RISKY":
            continue

        qty = min(row["Safe Qty"], int(gp / row["Buy"]))
        if qty <= 0:
            continue

        portfolio.append({
            "Item": row["Item"],
            "Qty": qty,
            "Buy": row["Buy"],
            "Sell": row["Sell"],
            "Profit": qty * row["Margin"]
        })

    return pd.DataFrame(portfolio)

# ---------- WATCHLIST ----------
def render_watchlist():
    st.sidebar.header("👁️ Watchlist")

    if "watchlist" not in st.session_state:
        st.session_state.watchlist = load_watchlist()

    for i, row in enumerate(st.session_state.watchlist):
        st.sidebar.write(f"{row['Item']} ({row['Entry']}→{row['Exit']})")

# ---------- MAIN ----------
st.set_page_config(layout="wide")
st.title("📊 OSRS GE AI Flipping Dashboard")

if st.button("🔄 Refresh Prices"):
    st.cache_data.clear()
    st.rerun()

gp = st.number_input("💰 Your GP", value=10_000_000)

profit_mode = st.toggle("🔥 Profit Mode (Longer Holds, Higher Margins)")

prices, volumes, names, limits = fetch_data()

# SEARCH
st.subheader("🔎 Item Analyzer")
search = st.text_input("Search item")

if search:
    res = analyze_item(search, prices, volumes, names, limits)
    if res:
        st.write(res)

# TABLE
df = calculate_flips(prices, volumes, names, limits, profit_mode)

st.subheader("🧠 Portfolio")
st.dataframe(optimize_portfolio(df, gp))

st.subheader("📈 Opportunities")
st.dataframe(df.head(30))

render_watchlist()
