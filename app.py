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
                data = json.load(f)
                return data
            except json.JSONDecodeError:
                return []
    return []

# ---------- CALCULATIONS ----------
def calculate_flips(prices, volumes, names, limits, min_volume=MIN_VOLUME, min_margin=MIN_MARGIN, high_volume=False):
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
        volume_score = min(volume / 100_000, 1)
        margin_score = min(real_margin / 1000, 1)
        roi_score = min(roi / 0.1, 1)
        confidence_score = round((volume_score + margin_score + roi_score)/3*100,1)

        if high_volume and (real_margin > 100 or volume < 2000):
            continue

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
    df = pd.DataFrame(rows)
    return df.sort_values(by="Profit per Hour", ascending=False).head(20)

def calculate_speculative(prices, volumes, names, limits):
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
        if low < high * 0.9:
            buy_limit = limits.get(item_id, 0)
            real_sell = high * (1 - GE_TAX)
            real_margin = real_sell - low
            profit_per_limit = real_margin * buy_limit
            fills_per_hour = volume / 24
            time_to_sell_hours = min(buy_limit / fills_per_hour, BUY_LIMIT_HOURS) if fills_per_hour>0 else 0.1
            profit_per_hour = profit_per_limit / max(time_to_sell_hours,0.1)
            roi = real_margin / low
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
    df = pd.DataFrame(rows)
    return df.sort_values(by="Confidence", ascending=False).head(20)

# ---------- DISPLAY ----------
def render_table(df, table_key):
    for idx, row in df.iterrows():
        cols = st.columns([0.5,2,1,1,1,1,1,1,1,1,1,0.5])
        cols[0].markdown(f'<img src="{row["Image"]}" width="30">', unsafe_allow_html=True)
        cols[1].write(row["Item"])
        cols[2].markdown(f'<span style="color:green">{row["Buy"]}</span>', unsafe_allow_html=True)
        cols[3].markdown(f'<span style="color:red">{row["Sell"]}</span>', unsafe_allow_html=True)
        margin_color = f"green" if row["Margin"] > 0 else "red"
        cols[4].markdown(f'<span style="color:{margin_color}">{row["Margin"]}</span>', unsafe_allow_html=True)
        cols[5].markdown(f'<span style="color:gray">{row["ROI %"]}</span>', unsafe_allow_html=True)
        cols[6].markdown(f'<span style="color:gray">{row["Volume"]}</span>', unsafe_allow_html=True)
        cols[7].markdown(f'<span style="color:gray">{row["Buy Limit"]}</span>', unsafe_allow_html=True)
        cols[8].markdown(f'<span style="color:gray">{row["Profit per Limit"]}</span>', unsafe_allow_html=True)
        cols[9].markdown(f'<span style="color:gray">{row["Profit per Hour"]}</span>', unsafe_allow_html=True)
        cols[10].markdown(f'<span style="color:gray">{row["Confidence"]}</span>', unsafe_allow_html=True)
        if st.button(f"➕", key=f"{table_key}_{idx}"):
            if "watchlist" not in st.session_state:
                st.session_state.watchlist = load_watchlist()
            # Avoid duplicates
            if row["Item"] not in [w["Item"] for w in st.session_state.watchlist]:
                st.session_state.watchlist.append({
                    "Item": row["Item"],
                    "Image": row["Image"],
                    "Buy": row["Buy"],
                    "Sell": row["Sell"],
                    "Volume": row["Volume"]
                })
                save_watchlist(st.session_state.watchlist)
                st.session_state.rerun_key = st.session_state.get("rerun_key", 0) + 1
                st.experimental_rerun()

# ---------- WATCHLIST ----------
def render_watchlist():
    st.sidebar.header("👁️ Watchlist")
    watchlist = st.session_state.get("watchlist", load_watchlist())
    if not watchlist:
        st.sidebar.write("No trades added yet.")
        return
    for idx, item in enumerate(watchlist):
        cols = st.sidebar.columns([1,2,1,1,1])
        cols[0].markdown(f'<img src="{item["Image"]}" width="30">', unsafe_allow_html=True)
        cols[1].write(item["Item"])
        cols[2].write(f"Buy: {item['Buy']}")
        cols[3].write(f"Sell: {item['Sell']}")
        cols[4].write(f"Vol: {item['Volume']}")
        if st.sidebar.button(f"❌", key=f"rm_{idx}"):
            st.session_state.watchlist.pop(idx)
            save_watchlist(st.session_state.watchlist)
            st.session_state.rerun_key = st.session_state.get("rerun_key", 0) + 1
            st.experimental_rerun()

# ---------- MAIN ----------
st.set_page_config(page_title="OSRS GE Dashboard", layout="wide")
st.title("📊 OSRS GE Dashboard")

prices, volumes, names, limits = fetch_data()
if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist()

st.subheader("💰 Regular Profitable Trades")
regular_df = calculate_flips(prices, volumes, names, limits)
if not regular_df.empty:
    render_table(regular_df, "regular")

st.subheader("🔵 High Volume Flips")
highvol_df = calculate_flips(prices, volumes, names, limits, min_volume=2000, min_margin=5, high_volume=True)
if not highvol_df.empty:
    render_table(highvol_df, "highvol")

st.subheader("🟣 Speculative / Underpriced Trades")
spec_df = calculate_speculative(prices, volumes, names, limits)
if not spec_df.empty:
    render_table(spec_df, "speculative")

render_watchlist()
