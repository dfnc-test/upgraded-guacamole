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
def calculate_trades(prices, volumes, names, limits, table_type):
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

        # Apply table-specific filters
        if table_type=="regular":
            if real_margin < 50 or roi < 0.005: continue
        elif table_type=="highvolume":
            if volume < 2000 or real_margin < 10: continue
        elif table_type=="speculative":
            if confidence_score < 50: continue

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
    return pd.DataFrame(rows)

# ---------- TABLE RENDERING ----------
def render_table(df, table_key):
    if df.empty:
        st.write("No trades found.")
        return

    st.markdown(
        """
        <style>
        .trade-table {border-collapse: collapse; width: 100%;}
        .trade-table th, .trade-table td {padding: 4px 6px; font-size: 13px; text-align:center; vertical-align: middle;}
        .trade-table th {background-color: #f2f2f2;}
        .trade-table td img {vertical-align: middle;}
        .add-btn {width:30px; height:30px; text-align:center;}
        </style>
        """, unsafe_allow_html=True
    )

    st.markdown("<table class='trade-table'>", unsafe_allow_html=True)
    # Headers
    st.markdown("<tr>"
                "<th></th><th>Item</th><th>Buy</th><th>Sell</th><th>Margin</th><th>ROI %</th>"
                "<th>Volume</th><th>Buy Limit</th><th>Profit/Limit</th><th>Profit/Hr</th><th>Conf</th><th>Add</th>"
                "</tr>", unsafe_allow_html=True)

    for idx, row in df.iterrows():
        margin_color = f"rgb({max(0,150-abs(row['Margin']))},{min(150,row['Margin'])},0)"
        st.markdown(f"<tr>"
                    f"<td><img src='{row['Image']}' width='25'></td>"
                    f"<td style='text-align:left'>{row['Item']}</td>"
                    f"<td style='color:green'>{row['Buy']}</td>"
                    f"<td style='color:red'>{row['Sell']}</td>"
                    f"<td style='color:{margin_color}'>{row['Margin']}</td>"
                    f"<td style='color:#555'>{row['ROI %']}</td>"
                    f"<td style='color:#555'>{row['Volume']}</td>"
                    f"<td style='color:#555'>{row['Buy Limit']}</td>"
                    f"<td style='color:#555'>{row['Profit per Limit']}</td>"
                    f"<td style='color:#555'>{row['Profit per Hour']}</td>"
                    f"<td style='color:#555'>{row['Confidence']}</td>"
                    f"<td class='add-btn'>{st.button('➕', key=f'{table_key}_{idx}')}</td>"
                    f"</tr>", unsafe_allow_html=True)
        # Watchlist add logic
        if st.session_state.get(f'{table_key}_{idx}', False):
            if "watchlist" not in st.session_state: st.session_state.watchlist = load_watchlist()
            if row["Item"] not in [w["Item"] for w in st.session_state.watchlist]:
                st.session_state.watchlist.append({
                    "Item": row["Item"],
                    "Image": row["Image"],
                    "Buy": row["Buy"],
                    "Sell": row["Sell"],
                    "Volume": row["Volume"]
                })
                save_watchlist(st.session_state.watchlist)

    st.markdown("</table>", unsafe_allow_html=True)

# ---------- WATCHLIST ----------
def render_watchlist():
    st.sidebar.header("👁️ Watchlist")
    watchlist = st.session_state.get("watchlist", load_watchlist())
    if not watchlist:
        st.sidebar.write("No trades added yet.")
        return

    for idx, row in enumerate(watchlist):
        st.sidebar.markdown(
            f"<div style='display:flex; align-items:center; padding:6px; margin-bottom:4px; border:1px solid #ccc; border-radius:5px;'>"
            f"<img src='{row['Image']}' width='35' style='margin-right:8px;'>"
            f"<div style='flex:1'>{row['Item']}</div>"
            f"<div style='color:green; margin-right:5px'>{row['Buy']}</div>"
            f"<div style='color:red; margin-right:5px'>{row['Sell']}</div>"
            f"<div style='color:#555'>{row['Volume']}</div>"
            f"<div>{st.button('❌', key=f'remove_{idx}')}</div>"
            f"</div>", unsafe_allow_html=True
        )
        if st.session_state.get(f'remove_{idx}', False):
            st.session_state.watchlist.pop(idx)
            save_watchlist(st.session_state.watchlist)
            st.session_state[f'remove_{idx}'] = False

# ---------- MAIN ----------
st.set_page_config(page_title="OSRS GE Dashboard", layout="wide")
st.title("📊 OSRS GE Dashboard")

prices, volumes, names, limits = fetch_data()
if "watchlist" not in st.session_state: st.session_state.watchlist = load_watchlist()

st.subheader("💰 Regular Profitable Trades")
regular_df = calculate_trades(prices, volumes, names, limits, "regular")
render_table(regular_df, "regular")

st.subheader("🟢 High Volume Flips")
highvol_df = calculate_trades(prices, volumes, names, limits, "highvolume")
render_table(highvol_df, "highvol")

st.subheader("🔵 Speculative Trades")
speculative_df = calculate_trades(prices, volumes, names, limits, "speculative")
render_table(speculative_df, "speculative")

render_watchlist()
