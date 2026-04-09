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

# ---------- CORE ANALYZER ----------
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
    if not high or not low:
        return None

    volume = volumes.get(str(item_id), {}).get("highPriceVolume", 0) + \
             volumes.get(str(item_id), {}).get("lowPriceVolume", 0)

    buy_limit = limits.get(item_id, 0)

    hist = fetch_history(item_id)
    if hist is None or len(hist) < 10:
        return None

    # ---- Trends ----
    short_momentum = (hist.iloc[-1] - hist.iloc[-3]) / hist.iloc[-3]
    medium_momentum = (hist.iloc[-1] - hist.iloc[-8]) / hist.iloc[-8]
    volatility = hist.pct_change().std()

    # ---- Margin ----
    real_sell = high * (1 - GE_TAX)
    margin = real_sell - low
    spread_pct = (high - low) / low

    # ---- Liquidity ----
    fills_per_hour = volume / 24 if volume > 0 else 1

    # ---- Sentiment ----
    sentiment = 0
    sentiment += 20 if short_momentum > 0 else 0
    sentiment += 20 if medium_momentum > 0 else 0
    sentiment += 20 if spread_pct > 0.03 else 0
    sentiment += 20 if volume > 50000 else 0
    sentiment += 20 if volatility < 0.02 else 0
    sentiment = min(sentiment, 100)

    # ---- Entry / Exit ----
    entry_price = int(low * 1.01)
    exit_price = int(real_sell * 0.99)

    # ---- Hold Time ----
    hold_hours = max(1, min(48, int((1 / max(fills_per_hour, 1)) * 10)))

    # ---- Score ----
    score = 0
    score += 30 if margin > 0 else 0
    score += 20 if spread_pct > 0.02 else 0
    score += 20 if sentiment > 60 else 0
    score += 15 if volume > 20000 else 0
    score += 15 if volatility < 0.03 else 0
    score = min(score, 100)

    # ---- Recommendation ----
    if score > 75:
        rec = "🔥 STRONG BUY / FLIP"
    elif score > 50:
        rec = "✅ GOOD OPPORTUNITY"
    elif score > 30:
        rec = "⚠️ SPECULATIVE"
    else:
        rec = "❌ AVOID"

    return {
        "Item": item_name,
        "Entry": entry_price,
        "Exit": exit_price,
        "Margin": int(margin),
        "Volume": volume,
        "Volatility": round(volatility, 4),
        "Momentum Short": round(short_momentum, 4),
        "Momentum Medium": round(medium_momentum, 4),
        "Hold": hold_hours,
        "Sentiment": sentiment,
        "Score": score,
        "Recommendation": rec,
        "Image": get_image_url(item_name)
    }

# ---------- EXISTING CALC ----------
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

        fills_per_hour = volume / 24 if volume > 0 else 1
        safe_qty = int(fills_per_hour * 2 * 0.3)
        safe_qty = min(buy_limit, safe_qty)

        if safe_qty < 5:
            continue

        time_to_sell = max(safe_qty / fills_per_hour, 0.1)
        profit_hour = (margin * safe_qty) / time_to_sell

        rows.append({
            "Item": names.get(item_id, "Unknown"),
            "Buy": int(low),
            "Sell": int(real_sell),
            "Margin": int(margin),
            "Volume": volume,
            "Safe Qty": safe_qty,
            "Profit/Hr": int(profit_hour),
            "Image": get_image_url(names.get(item_id, "Unknown"))
        })

    return pd.DataFrame(rows).sort_values(by="Profit/Hr", ascending=False)

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
st.title("📊 OSRS GE AI Flipping Dashboard")

if st.button("🔄 Refresh Prices"):
    st.cache_data.clear()
    st.rerun()

st.caption(f"Updated: {datetime.now().strftime('%H:%M:%S')}")

gp = st.number_input("💰 Your GP", value=10_000_000, step=1_000_000)

prices, volumes, names, limits = fetch_data()

# ---------- SEARCH ----------
st.subheader("🔎 Item Flip Analyzer")

search = st.text_input("Search item (exact name)")

if search:
    res = analyze_item(search, prices, volumes, names, limits)

    if res:
        st.image(res["Image"], width=50)
        st.markdown(f"## {res['Item']}")

        c1, c2, c3 = st.columns(3)
        c1.metric("Entry", res["Entry"])
        c2.metric("Exit", res["Exit"])
        c3.metric("Margin", res["Margin"])

        c1.metric("Hold (hrs)", res["Hold"])
        c2.metric("Score", res["Score"])
        c3.metric("Sentiment", res["Sentiment"])

        st.write(f"**{res['Recommendation']}**")

        if st.button("➕ Add to Watchlist"):
            if "watchlist" not in st.session_state:
                st.session_state.watchlist = []

            st.session_state.watchlist.append(res)
            save_watchlist(st.session_state.watchlist)
            st.success("Added!")

    else:
        st.warning("Item not found or insufficient data.")

# ---------- TABLE ----------
st.subheader("📈 Top Flips")
df = calculate_flips(prices, volumes, names, limits)
st.dataframe(df.head(30))

render_watchlist()
