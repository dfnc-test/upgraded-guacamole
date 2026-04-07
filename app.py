import streamlit as st
import requests
import pandas as pd
import json
import os

# ---------- CONFIG ----------
LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
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

def save_watchlist(watchlist):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(watchlist, f)

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, "r") as f:
            try: return json.load(f)
            except: return []
    return []

# ---------- CALCULATIONS ----------
def calculate_flips(prices, volumes, names, limits):
    rows = []
    for item_id, data in prices.items():
        item_id = int(item_id)
        high, low = data.get("high"), data.get("low")
        if not high or not low or low <= 0: continue
        vol_data = volumes.get(str(item_id), {})
        volume = vol_data.get("highPriceVolume",0) + vol_data.get("lowPriceVolume",0)
        if volume < MIN_VOLUME: continue
        real_sell = high * (1 - GE_TAX)
        real_margin = real_sell - low
        if real_margin < MIN_MARGIN: continue
        roi = real_margin / low
        buy_limit = limits.get(item_id, 0)
        profit_per_limit = real_margin * buy_limit
        fills_per_hour = volume / 24
        time_to_sell_hours = min(buy_limit / fills_per_hour, BUY_LIMIT_HOURS) if fills_per_hour>0 else 0.1
        profit_per_hour = profit_per_limit / max(time_to_sell_hours,0.1)
        volume_score = min(volume / 100_000, 1)
        margin_score = min(real_margin / 1000, 1)
        roi_score = min(roi / 0.1, 1)
        confidence_score = round((volume_score + margin_score + roi_score)/3*100,1)
        rows.append({
            "Image": get_image_url(names.get(item_id,"Unknown")),
            "Item": names.get(item_id,"Unknown"),
            "Buy": low,
            "Sell": int(real_sell),
            "Margin": int(real_margin),
            "ROI %": round(roi*100,2),
            "Volume": volume,
            "Buy Limit": buy_limit,
            "Profit per Limit": int(profit_per_limit),
            "Profit per Hour": int(profit_per_hour),
            "Confidence": confidence_score
        })
    return pd.DataFrame(rows).sort_values(by="Profit per Hour", ascending=False).head(20)

# ---------- UI TABLE WITH ADD BUTTONS ----------
def render_table_with_add(df, table_key):
    if df.empty: 
        st.write("No trades found.")
        return

    # Table headers
    headers = ["", "Item", "Buy", "Sell", "Margin", "ROI %", "Volume", "Buy Limit", "Profit/Limit", "Profit/Hr", "Conf", "Add"]

    st.markdown(
        f"""
        <style>
        .tight td {{padding:2px 5px;}}
        .tight th {{padding:2px 5px;}}
        </style>
        """, unsafe_allow_html=True)

    # Iterate rows
    for idx, row in df.iterrows():
        # Columns layout
        cols = st.columns([0.1,2,1,1,1,1,1,1,1,1,0.5,0.3])
        # Image
        with cols[0]: st.markdown(f'<img src="{row["Image"]}" width="20" style="vertical-align:middle">', unsafe_allow_html=True)
        # Item
        with cols[1]: st.write(row["Item"])
        # Buy green
        with cols[2]: st.markdown(f'<span style="color:green">{row["Buy"]}</span>', unsafe_allow_html=True)
        # Sell red
        with cols[3]: st.markdown(f'<span style="color:red">{row["Sell"]}</span>', unsafe_allow_html=True)
        # Margin gradient
        margin_color = "red" if row["Margin"]<0 else f"rgb(0,{min(row['Margin'],200)},0)"
        with cols[4]: st.markdown(f'<span style="color:{margin_color}">{row["Margin"]}</span>', unsafe_allow_html=True)
        # ROI, Volume, Buy Limit, Profit per limit, Profit per hour, Confidence
        with cols[5]: st.write(row["ROI %"])
        with cols[6]: st.write(row["Volume"])
        with cols[7]: st.write(row["Buy Limit"])
        with cols[8]: st.write(row["Profit per Limit"])
        with cols[9]: st.write(row["Profit per Hour"])
        with cols[10]: st.write(row["Confidence"])
        # Add button
        with cols[11]:
            if st.button("➕", key=f"{table_key}_{idx}"):
                if "watchlist" not in st.session_state: st.session_state.watchlist = load_watchlist()
                if row["Item"] not in [w["Item"] for w in st.session_state.watchlist]:
                    st.session_state.watchlist.append(row.to_dict())
                    save_watchlist(st.session_state.watchlist)
                st.session_state.table_updated = True  # trigger rerun via session_state

# ---------- WATCHLIST ----------
def render_watchlist():
    st.sidebar.header("👁️ Watchlist")
    watchlist = st.session_state.get("watchlist", load_watchlist())
    if not watchlist:
        st.sidebar.write("No trades added yet.")
        return
    for idx, row in enumerate(watchlist):
        cols = st.sidebar.columns([0.1,2,1,1,1,1,1,1,1,1,0.5])
        with cols[0]: st.sidebar.markdown(f'<img src="{row["Image"]}" width="20">', unsafe_allow_html=True)
        with cols[1]: st.sidebar.write(row["Item"])
        with cols[2]: st.sidebar.markdown(f'<span style="color:green">{row["Buy"]}</span>', unsafe_allow_html=True)
        with cols[3]: st.sidebar.markdown(f'<span style="color:red">{row["Sell"]}</span>', unsafe_allow_html=True)
        margin_color = "red" if row["Margin"]<0 else f"rgb(0,{min(row['Margin'],200)},0)"
        with cols[4]: st.sidebar.markdown(f'<span style="color:{margin_color}">{row["Margin"]}</span>', unsafe_allow_html=True)
        with cols[5]: st.sidebar.write(row["ROI %"])
        with cols[6]: st.sidebar.write(row["Volume"])
        with cols[7]: st.sidebar.write(row["Buy Limit"])
        with cols[8]: st.sidebar.write(row["Profit per Limit"])
        with cols[9]: st.sidebar.write(row["Profit per Hour"])
        with cols[10]:
            if st.sidebar.button("❌", key=f"remove_{idx}"):
                st.session_state.watchlist.pop(idx)
                save_watchlist(st.session_state.watchlist)
                st.session_state.table_updated = True

# ---------- MAIN ----------
st.set_page_config(page_title="OSRS GE Dashboard", layout="wide")
st.title("📊 OSRS GE Dashboard")

prices, volumes, names, limits = fetch_data()
if "watchlist" not in st.session_state: st.session_state.watchlist = load_watchlist()
if "table_updated" not in st.session_state: st.session_state.table_updated = False

st.subheader("💰 Regular Profitable Trades")
regular_df = calculate_flips(prices, volumes, names, limits)
render_table_with_add(regular_df, "regular")

st.subheader("🟢 High Volume Flips")
high_vol_df = regular_df.sort_values("Volume", ascending=False).head(20)
render_table_with_add(high_vol_df, "highvol")

st.subheader("🔵 Speculative Trades")
speculative_df = regular_df.sort_values("Confidence", ascending=False).head(20)
render_table_with_add(speculative_df, "speculative")

render_watchlist()

# Rerun logic
if st.session_state.table_updated:
    st.session_state.table_updated = False
    st.experimental_rerun()
