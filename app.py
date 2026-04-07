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

        # High-volume flips filter (small margin, high volume)
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
    # Compare current low price vs high price in the last 24h
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
        # If current low is 10% below the 24h high, it's potentially underpriced
        if low > 0 and high > 0 and low < high * 0.9:
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
def render_table_with_add_buttons(df, table_key):
    df = df.copy()
    df["Image"] = df["Image"].apply(lambda url: f'<img src="{url}" width="20" style="vertical-align:middle">')
    df["Add"] = ""
    cols = df.columns.tolist()
    cols.insert(0, cols.pop(cols.index("Image")))
    cols.append(cols.pop(cols.index("Add")))
    df = df[cols]

    base_html = df.drop(columns=["Add"]).to_html(escape=False, index=False)
    rows_html = base_html.split("</tr>")
    header = rows_html[0].replace("</tr>", "<th>Add</th></tr>")
    new_rows_html = [header]

    for i, row_html in enumerate(rows_html[1:-1]):
        button_html = f'<td><button id="{table_key}_add_{i}">Add</button></td>'
        new_row = row_html + button_html + "</tr>"
        new_rows_html.append(new_row)
    new_rows_html.append(rows_html[-1])
    final_html = "".join(new_rows_html)
    st.markdown(final_html, unsafe_allow_html=True)

# ---------- WATCHLIST ----------
def render_watchlist():
    st.sidebar.header("👁️ Watchlist")
    watchlist = st.session_state.get("watchlist", load_watchlist())
    if not watchlist:
        st.sidebar.write("No trades added yet.")
        return
    df_watchlist = pd.DataFrame(watchlist)
    df_watchlist["Image"] = df_watchlist["Image"].apply(lambda url: f'<img src="{url}" width="20" style="vertical-align:middle">')
    cols = df_watchlist.columns.tolist()
    cols.insert(0, cols.pop(cols.index("Image")))
    df_watchlist = df_watchlist[cols]
    st.sidebar.markdown(df_watchlist.to_html(escape=False, index=False), unsafe_allow_html=True)
    for idx, row in df_watchlist.iterrows():
        btn_key = f"remove_btn_{idx}"
        if st.sidebar.button(f"❌ Remove '{row['Item']}'", key=btn_key):
            st.session_state.watchlist.pop(idx)
            save_watchlist(st.session_state.watchlist)
            st.experimental_rerun()

# ---------- MAIN ----------
st.set_page_config(page_title="OSRS GE Dashboard", layout="wide")
st.title("📊 OSRS GE Dashboard with Watchlist Buttons")

prices, volumes, names, limits = fetch_data()
if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist()

# Regular profitable flips
st.subheader("💰 Regular Profitable Trades")
regular_df = calculate_flips(prices, volumes, names, limits)
if regular_df.empty:
    st.write("No regular trades found.")
else:
    render_table_with_add_buttons(regular_df, "regular")

# High-volume flips
st.subheader("🔵 High Volume Flips")
highvol_df = calculate_flips(prices, volumes, names, limits, min_volume=2000, min_margin=5, high_volume=True)
if highvol_df.empty:
    st.write("No high-volume flips found.")
else:
    render_table_with_add_buttons(highvol_df, "highvol")

# Speculative / underpriced trades
st.subheader("🟣 Speculative / Underpriced Trades")
spec_df = calculate_speculative(prices, volumes, names, limits)
if spec_df.empty:
    st.write("No speculative trades found.")
else:
    render_table_with_add_buttons(spec_df, "speculative")

render_watchlist()
