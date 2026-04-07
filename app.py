import streamlit as st
import requests
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta

# ---------- CONFIG ----------
LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
HISTORY_URL = "https://prices.runescape.wiki/api/v1/osrs/timeseries"

HEADERS = {"User-Agent": "osrs-ge-dashboard (redsnowcp@gmail.com)"}

GE_TAX = 0.05
MIN_VOLUME = 500
MIN_MARGIN = 20
BUY_LIMIT_HOURS = 4
WATCHLIST_FILE = "watchlist.json"

# ---------- HELPERS ----------
def get_image_url(name):
    formatted = name.replace(" ", "_").replace("'", "").replace("(", "").replace(")", "")
    return f"https://oldschool.runescape.wiki/images/{formatted}.png"

@st.cache_data(ttl=60)
def fetch_data():
    prices = requests.get(LATEST_URL, headers=HEADERS, timeout=10).json()["data"]
    volumes = requests.get(VOLUME_URL, headers=HEADERS, timeout=10).json()["data"]
    mapping = requests.get(MAPPING_URL, headers=HEADERS, timeout=10).json()
    id_to_name = {item["id"]: item["name"] for item in mapping}
    id_to_limit = {item["id"]: item.get("limit", 0) for item in mapping}
    return prices, volumes, id_to_name, id_to_limit

def fetch_history(item_id, days=7):
    """Fetch historical data and validate."""
    try:
        start_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        url = f"https://prices.runescape.wiki/api/v1/osrs/timeseries?start={start_date}&item={item_id}"
        res = requests.get(url, headers=HEADERS, timeout=10).json()
        data = res.get("data", {}).get(str(item_id), [])

        prices = []
        for point in data:
            high = point.get("avgHighPrice", 0)
            low = point.get("avgLowPrice", 0)
            if high > 0 and low > 0:
                prices.append((high + low)/2)
            elif high > 0:
                prices.append(high)
            elif low > 0:
                prices.append(low)

        # Validation: require at least 10 distinct points
        prices = [p for p in prices if p > 0]
        if len(prices) < 10 or np.std(prices) == 0:
            return None

        return pd.Series(prices)
    except:
        return None

def save_watchlist(watchlist):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(watchlist, f)

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, "r") as f:
            try:
                return json.load(f)
            except:
                return []
    return []

# ---------- CALCULATIONS ----------
def calculate_flips(prices, volumes, names, limits):
    rows = []

    for item_id, data in prices.items():
        item_id = int(item_id)
        high, low = data.get("high"), data.get("low")
        if not high or not low or low <= 0:
            continue

        vol_data = volumes.get(str(item_id), {})
        volume = vol_data.get("highPriceVolume",0) + vol_data.get("lowPriceVolume",0)
        if volume < MIN_VOLUME:
            continue

        real_sell = high * (1 - GE_TAX)
        margin = real_sell - low
        if margin < MIN_MARGIN:
            continue

        roi = margin / low
        buy_limit = limits.get(item_id, 0)
        profit_limit = margin * buy_limit
        fills_per_hour = volume / 24
        time_to_sell = min(buy_limit / fills_per_hour, BUY_LIMIT_HOURS) if fills_per_hour>0 else 0.1
        profit_hour = profit_limit / max(time_to_sell, 0.1)

        # ---------- HISTORICAL DATA ----------
        hist = fetch_history(item_id, days=7)
        if hist is not None:
            z = (low - hist.mean()) / hist.std()
            high_7d = hist.max()
            low_7d = hist.min()
        else:
            z = np.nan
            high_7d = low_7d = 0

        # ---------- INDICATORS ----------
        mid_price = (high + low) / 2
        sma = mid_price
        ema = (mid_price * 0.7) + (low * 0.3)
        momentum = ((high - low) / low) * 100 if low > 0 else 0
        vol_spike = min(volume / 10000, 5)

        # ---------- SIGNAL ----------
        if pd.isna(z):
            signal = "HOLD"
        elif z < -1 and vol_spike > 1:
            signal = "BUY"
        elif z > 1:
            signal = "SELL"
        else:
            signal = "HOLD"

        # ---------- CONFIDENCE ----------
        volume_score = min(volume / 100000, 1)
        margin_score = min(margin / 1000, 1)
        roi_score = min(roi / 0.1, 1)
        confidence = round((volume_score + margin_score + roi_score)/3*100,1)

        rows.append({
            "Image": get_image_url(names.get(item_id,"Unknown")),
            "Item": names.get(item_id,"Unknown"),
            "Buy": low,
            "Sell": int(real_sell),
            "Margin": int(margin),
            "ROI %": round(roi*100,2),
            "Volume": volume,
            "Profit/Hr": int(profit_hour),
            "Conf": confidence,
            "SMA": int(sma),
            "EMA": int(ema),
            "Momentum": round(momentum,2),
            "Z": round(z,2) if not pd.isna(z) else "N/A",
            "Vol Spike": round(vol_spike,2),
            "7d High": int(high_7d),
            "7d Low": int(low_7d),
            "Signal": signal
        })

    return pd.DataFrame(rows).sort_values(by="Profit/Hr", ascending=False).head(20)

# ---------- DISPLAY WITH TOOLTIPS ----------
def render_table(df, key):
    tooltips = {
        "SMA":"Simple Moving Average: midpoint price of current data",
        "EMA":"Exponential Moving Average: weighted low/high",
        "Momentum":"Price change % from low to high",
        "Z":"Z-score vs 7-day historical average",
        "Vol Spike":"Volume spike relative to baseline",
        "7d High":"Highest price over past 7 days",
        "7d Low":"Lowest price over past 7 days",
        "Signal":"Trade recommendation based on indicators"
    }

    headers = ["Img","Item","Buy","Sell","Margin","ROI","Vol","P/H","Conf",
           "SMA","EMA","Mom","Z","Spike","7H","7L","Signal","+"]

    widths = [0.5,2,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0.4]

    cols = st.columns(widths)
    for c, h in zip(cols, headers):
        tooltip = tooltips.get(h, "")
        c.markdown(f"**{h}** <span style='font-size:10px;color:gray'>({tooltip})</span>", unsafe_allow_html=True)

    for i, row in df.iterrows():
        cols = st.columns(widths)

        cols[0].markdown(f'<img src="{row["Image"]}" width="25">', unsafe_allow_html=True)
        cols[1].markdown(f"**{row['Item']}**")
        cols[2].markdown(f"<span style='color:green'>{row['Buy']}</span>", unsafe_allow_html=True)
        cols[3].markdown(f"<span style='color:red'>{row['Sell']}</span>", unsafe_allow_html=True)
        mcolor = "green" if row["Margin"] > 0 else "red"
        cols[4].markdown(f"<span style='color:{mcolor}'>{row['Margin']}</span>", unsafe_allow_html=True)
        cols[5].markdown(row["ROI %"])
        cols[6].markdown(row["Volume"])
        cols[7].markdown(row["Profit/Hr"])
        cols[8].markdown(row["Conf"])
        cols[9].markdown(row["SMA"])
        cols[10].markdown(row["EMA"])
        cols[11].markdown(row["Momentum"])
        cols[12].markdown(row["Z"])
        cols[13].markdown(row["Vol Spike"])
        cols[14].markdown(row["7d High"])
        cols[15].markdown(row["7d Low"])
        sig = row["Signal"]
        color = "green" if sig=="BUY" else "red" if sig=="SELL" else "gray"
        cols[16].markdown(f"<span style='color:{color}'>{sig}</span>", unsafe_allow_html=True)

        if cols[16].button("+", key=f"{key}_{i}"):
            if "watchlist" not in st.session_state:
                st.session_state.watchlist = load_watchlist()
            if row["Item"] not in [w["Item"] for w in st.session_state.watchlist]:
                st.session_state.watchlist.append({
                    "Image": row["Image"],
                    "Item": row["Item"],
                    "Buy": row["Buy"],
                    "Sell": row["Sell"],
                    "Volume": row["Volume"]
                })
                save_watchlist(st.session_state.watchlist)

# ---------- WATCHLIST ----------
def render_watchlist():
    st.sidebar.header("👁️ Watchlist")
    wl = st.session_state.get("watchlist", load_watchlist())
    for i, row in enumerate(wl):
        st.sidebar.markdown(f"""
        <div style="border:1px solid #aaa; padding:6px; margin-bottom:6px; border-radius:6px; font-size:12px;">
            <img src="{row['Image']}" width="25">
            <b>{row['Item']}</b><br>
            <span style="color:green">Buy: {row['Buy']}</span><br>
            <span style="color:red">Sell: {row['Sell']}</span><br>
            Vol: {row['Volume']}
        </div>
        """, unsafe_allow_html=True)
        if st.sidebar.button("❌", key=f"rm_{i}"):
            wl.pop(i)
            save_watchlist(wl)

# ---------- MAIN ----------
st.set_page_config(layout="wide")
st.title("📊 OSRS GE Dashboard (Advanced Indicators + Tooltips)")

prices, volumes, names, limits = fetch_data()
df = calculate_flips(prices, volumes, names, limits)
render_table(df, "main")
render_watchlist()
