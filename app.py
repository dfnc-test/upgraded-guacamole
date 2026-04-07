import streamlit as st
import requests
import pandas as pd
import numpy as np
import json
import os
import random

# ---------- CONFIG ----------
LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"

HEADERS = {"User-Agent": "osrs-ge-dashboard (redsnowcp@gmail.com)"}

GE_TAX = 0.05
MIN_VOLUME = 500
HIGH_VOLUME_THRESHOLD = 50_000  # High volume filter
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

@st.cache_data(ttl=3600)
def fetch_history(item_id):
    """Fetch historical midpoint prices for Z-score."""
    try:
        url = f"https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep=1h&id={item_id}"
        res = requests.get(url, headers=HEADERS, timeout=10).json()
        data = res.get("data", {}).get(str(item_id), None)

        if not data:
            st.write(f"No historical data returned for item {item_id}")
            return None

        prices = []
        timestamps = []

        if isinstance(data, list):
            for point in data:
                timestamp = point.get("timestamp")
                high = point.get("avgHighPrice", 0)
                low = point.get("avgLowPrice", 0)
                if high > 0 and low > 0:
                    prices.append((high + low) / 2)
                elif high > 0:
                    prices.append(high)
                elif low > 0:
                    prices.append(low)
                if timestamp:
                    timestamps.append(timestamp)

        else:
            st.write(f"Unexpected data format for item {item_id}: {type(data)}")
            return None

        if not prices:
            st.write(f"No valid price points parsed for item {item_id}")
            return None

        timestamps_dt = pd.to_datetime(timestamps, unit='s', errors='coerce')
        series = pd.Series(prices, index=timestamps_dt)
        st.write(f"Fetched {len(series)} historical points for item {item_id}")
        return series

    except Exception as e:
        st.write(f"Error fetching history for {item_id}: {e}")
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

# ---------- DEBUG: Random Item Historical Table ----------
st.subheader("🛠️ Debug Z-Score for Random Item")
random_item_id = random.choice(list(prices.keys()))
random_item_data = prices[random_item_id]
high, low = random_item_data.get("high"), random_item_data.get("low")
mid_price = (high + low)/2 if high and low else None

if mid_price:
    hist = fetch_history(int(random_item_id))
    if hist is not None:
        z = (mid_price - hist.mean()) / hist.std(ddof=0) if hist.std(ddof=0) > 0 else 0
        st.write(f"Random Item {random_item_id}: Mid={mid_price}, Z={z:.2f}")
        st.dataframe(pd.DataFrame({"MidPrice": hist.values}, index=hist.index))
    else:
        st.write(f"No historical data parsed for item {random_item_id}")
else:
    st.write(f"Random item {random_item_id} has invalid prices")

if not hist_debug_shown:
    st.write("No historical data found for 10 random items. Z-scores will be unavailable.")

# ---------- CALCULATIONS ----------
def calculate_flips(prices, volumes, names, limits, min_vol=MIN_VOLUME):
    rows = []
    for item_id, data in prices.items():
        item_id = int(item_id)
        high, low = data.get("high"), data.get("low")
        if not high or not low or low <= 0:
            continue

        vol_data = volumes.get(str(item_id), {})
        volume = vol_data.get("highPriceVolume",0) + vol_data.get("lowPriceVolume",0)
        if volume < min_vol:
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

        mid_price = (high + low)/2
        sma = mid_price
        ema = (mid_price*0.7 + low*0.3)
        momentum = ((high-low)/low)*100 if low>0 else 0
        vol_spike = min(volume/10000,5)

        # ----- Z-SCORE using historical mid-prices -----
        hist = fetch_history(item_id)
        if hist is not None and len(hist) >= 3:
            hist_mean = hist.mean()
            hist_std = hist.std(ddof=0)
            z = (mid_price - hist_mean) / hist_std if hist_std > 0 else 0.0
        else:
            z = 0.0  # fallback if no history

        # ----- Signal based on Z-score -----
        if z < -0.5 and vol_spike > 1:
            signal = "BUY"
        elif z > 0.5:
            signal = "SELL"
        else:
            signal = "HOLD"

        # Confidence
        volume_score = min(volume / 100_000, 1)
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
            "Z": round(z,2) if not np.isnan(z) else "N/A",
            "Vol Spike": round(vol_spike,2),
            "Signal": signal
        })
    return pd.DataFrame(rows).sort_values(by="Profit/Hr", ascending=False).head(20)

# ---------- DISPLAY ----------
def render_table(df, key):
    headers = ["Img","Item","Buy","Sell","Margin","ROI","Vol","P/H","Conf",
               "SMA","EMA","Mom","Z","Spike","Signal","+"]

    widths = [0.5,2,1,1,1,1,1,1,1,1,1,1,1,1,1,0.4]

    cols = st.columns(widths)
    for c,h in zip(cols, headers):
        c.markdown(f"**{h}**")

    for i,row in df.iterrows():
        cols = st.columns(widths)
        cols[0].markdown(f'<img src="{row["Image"]}" width="25">', unsafe_allow_html=True)
        cols[1].markdown(f"**{row['Item']}**")
        cols[2].markdown(f"<span style='color:green'>{row['Buy']}</span>", unsafe_allow_html=True)
        cols[3].markdown(f"<span style='color:red'>{row['Sell']}</span>", unsafe_allow_html=True)
        mcolor = "green" if row["Margin"]>0 else "red"
        cols[4].markdown(f"<span style='color:{mcolor}'>{row['Margin']}</span>", unsafe_allow_html=True)
        cols[5].markdown(row["ROI %"])
        cols[6].markdown(row["Volume"])
        cols[7].markdown(row["Profit/Hr"])
        cols[8].markdown(row["Conf"])
        cols[9].markdown(row["SMA"])
        cols[10].markdown(row["EMA"])
        cols[11].markdown(row["Momentum"])
        zcolor = "green" if row["Signal"]=="BUY" else "red" if row["Signal"]=="SELL" else "gray"
        cols[12].markdown(row["Z"], unsafe_allow_html=True)
        cols[13].markdown(row["Vol Spike"])
        cols[14].markdown(f"<span style='color:{zcolor}'>{row['Signal']}</span>", unsafe_allow_html=True)

        if cols[15].button("+", key=f"{key}_{i}"):
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
    for i,row in enumerate(wl):
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
st.title("📊 OSRS GE Dashboard (High Volume Test)")

st.subheader("💰 Regular Profitable Trades")
df = calculate_flips(prices, volumes, names, limits)
render_table(df, "main")

st.subheader("📈 High Volume Items (Reliable Z)")
df_highvol = calculate_flips(prices, volumes, names, limits, min_vol=HIGH_VOLUME_THRESHOLD)
render_table(df_highvol, "highvol")

render_watchlist()
