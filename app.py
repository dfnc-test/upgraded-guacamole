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
    formatted = (
        name.replace(" ", "_")
        .replace("'", "")
        .replace("(", "")
        .replace(")", "")
    )
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
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

# ---------- CALCULATIONS ----------
def calculate_flips(prices, volumes, names, limits, min_margin=MIN_MARGIN, min_volume=MIN_VOLUME):
    rows = []
    for item_id, data in prices.items():
        item_id = int(item_id)
        high, low = data.get("high"), data.get("low")
        if not high or not low or low <= 0:
            continue
        vol_data = volumes.get(str(item_id), {})
        volume = vol_data.get("highPriceVolume",0) + vol_data.get("lowPriceVolume",0)
        if volume < min_volume:
            continue
        real_sell = high * (1 - GE_TAX)
        real_margin = real_sell - low
        if real_margin < min_margin:
            continue
        roi = real_margin / low
        buy_limit = limits.get(item_id, 0)
        profit_per_limit = real_margin * buy_limit
        fills_per_hour = volume / 24
        time_to_sell_hours = min(buy_limit / fills_per_hour, BUY_LIMIT_HOURS) if fills_per_hour>0 else 0.1
        profit_per_hour = profit_per_limit / max(time_to_sell_hours,0.1)
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
            "Profit per Hour": int(profit_per_hour)
        })
    return pd.DataFrame(rows)

# ---------- DISPLAY ----------
def render_table(df, table_key):
    df = df.copy()
    headers = ["Img","Item","Buy","Sell","Margin","ROI %","Volume","Buy Limit","Profit/Limit","Profit/Hr","Add"]
    col_widths = [0.5,2,1,1,1,1,1,1,1,1,0.3]
    st.write("")
    header_cols = st.columns(col_widths)
    for col, header in zip(header_cols, headers):
        col.markdown(f"**{header}**")
    for idx, row in df.iterrows():
        cols = st.columns(col_widths)
        cols[0].markdown(f'<img src="{row["Image"]}" width="25">', unsafe_allow_html=True)
        cols[1].markdown(f"**{row['Item']}**")
        cols[2].markdown(f"<span style='color:green'>{row['Buy']}</span>", unsafe_allow_html=True)
        cols[3].markdown(f"<span style='color:red'>{row['Sell']}</span>", unsafe_allow_html=True)
        margin_color = "green" if row['Margin'] > 0 else "red"
        cols[4].markdown(f"<span style='color:{margin_color}'>{row['Margin']}</span>", unsafe_allow_html=True)
        cols[5].markdown(f"{row['ROI %']}", unsafe_allow_html=True)
        cols[6].markdown(f"{row['Volume']}", unsafe_allow_html=True)
        cols[7].markdown(f"{row['Buy Limit']}", unsafe_allow_html=True)
        cols[8].markdown(f"{row['Profit per Limit']}", unsafe_allow_html=True)
        cols[9].markdown(f"{row['Profit per Hour']}", unsafe_allow_html=True)
        if cols[10].button("+", key=f"{table_key}_{idx}"):
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

def render_watchlist():
    st.sidebar.header("👁️ Watchlist")
    watchlist = st.session_state.get("watchlist", load_watchlist())
    if not watchlist:
        st.sidebar.write("No trades added yet.")
        return
    for idx, row in enumerate(watchlist):
        st.sidebar.markdown(
            f"""
            <div style="border:1px solid #aaa; padding:5px; margin-bottom:5px; border-radius:5px; font-size:12px;">
                <div style="display:flex; align-items:center;">
                    <img src="{row['Image']}" width="30" style="margin-right:5px;">
                    <div>
                        <b>{row['Item']}</b><br>
                        <span style="color:green">Buy: {row['Buy']}</span><br>
                        <span style="color:red">Sell: {row['Sell']}</span><br>
                        Volume: {row['Volume']}
                    </div>
                    <div style="margin-left:auto;">
                        <form>{""}</form>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True
        )
        if st.sidebar.button("❌", key=f"remove_{idx}"):
            st.session_state.watchlist.pop(idx)
            save_watchlist(st.session_state.watchlist)

# ---------- MAIN ----------
st.set_page_config(page_title="OSRS GE Dashboard", layout="wide")
st.title("📊 OSRS GE Dashboard")

prices, volumes, names, limits = fetch_data()
if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist()

# Regular profitable flips
st.subheader("💰 Regular Profitable Trades")
regular_df = calculate_flips(prices, volumes, names, limits)
if regular_df.empty:
    st.write("No regular trades found.")
else:
    render_table(regular_df.sort_values(by="Profit per Hour", ascending=False).head(20), "regular")

# High volume flips
st.subheader("📈 High Volume Flips")
highvol_df = calculate_flips(prices, volumes, names, limits, min_margin=5, min_volume=2000)
if highvol_df.empty:
    st.write("No high volume flips found.")
else:
    render_table(highvol_df.sort_values(by="Volume", ascending=False).head(20), "highvol")

# Speculative trades (low price items that may be underpriced)
st.subheader("🔮 Speculative Trades")
spec_df = calculate_flips(prices, volumes, names, limits, min_margin=5, min_volume=50)
spec_df = spec_df[spec_df["ROI %"] > 0]  # filter profitable speculative trades
if spec_df.empty:
    st.write("No speculative trades found.")
else:
    render_table(spec_df.sort_values(by="ROI %", ascending=False).head(20), "spec")

# Render watchlist
render_watchlist()
