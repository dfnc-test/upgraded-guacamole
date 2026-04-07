import streamlit as st
import requests
import pandas as pd

# ================= CONFIG =================
LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"

HEADERS = {"User-Agent": "GE-Trading-Dashboard redsnowcp@gmail.com"}

STOP_LOSS_PCT = 0.03
TAKE_PROFIT_PCT = 0.05
HIGH_VALUE_THRESHOLD = 1_000_000
# ==========================================

# ---------- Helpers ----------
def get_image_url(name):
    formatted = name.replace(" ", "_").replace("'", "").replace("(", "").replace(")", "")
    return f"https://oldschool.runescape.wiki/images/{formatted}.png"

@st.cache_data(ttl=60)
def fetch_data():
    prices = requests.get(LATEST_URL, headers=HEADERS, timeout=5).json()["data"]
    volumes = requests.get(VOLUME_URL, headers=HEADERS, timeout=5).json()["data"]
    mapping = requests.get(MAPPING_URL, headers=HEADERS, timeout=5).json()
    id_to_name = {item["id"]: item["name"] for item in mapping}
    return prices, volumes, id_to_name

def analyze_items(prices, volumes, names, capital, mode):
    rows = []

    # Mode filters
    if mode == "Safe":
        min_volume, min_margin, min_roi, max_real_roi, max_fill_time = 1000, 50, 0.005, 0.08, 2
    else:
        min_volume, min_margin, min_roi, max_real_roi, max_fill_time = 100, 20, 0.002, 0.15, 6

    for item_id, data in prices.items():
        item_id = int(item_id)
        high = data.get("high")
        low = data.get("low")
        vol_data = volumes.get(str(item_id), {})
        vol = vol_data.get("volume", 0) or vol_data.get("high", 0)
        if not high or not low or low == 0 or vol < min_volume:
            continue

        margin = high - low
        roi = margin / low
        if margin < min_margin or roi < min_roi:
            continue

        # Realistic prices
        real_buy = int(low * 1.01)
        real_sell = int(high * 0.99 * 0.985)  # GE tax
        real_margin = real_sell - real_buy
        if real_margin <= 0:
            continue
        real_roi = real_margin / real_buy
        if real_roi > max_real_roi:
            continue

        fills_per_hour = vol / 24
        trade_size = min(capital // real_buy, int(vol * 0.1))
        if fills_per_hour == 0 or trade_size == 0:
            continue
        time_to_fill = trade_size / fills_per_hour
        if time_to_fill > max_fill_time:
            continue

        stop_loss = int(real_buy * (1 - STOP_LOSS_PCT))
        take_profit = int(real_buy * (1 + TAKE_PROFIT_PCT))
        buy_limit = vol // 6
        profit_per_hour = round(real_margin * fills_per_hour, 2)
        profit_per_limit = round(real_margin * buy_limit, 2)
        confidence = round((vol / 1000) * real_roi * real_margin, 2)

        rows.append({
            "Item": names.get(item_id, "Unknown"),
            "Buy": real_buy,
            "Sell": real_sell,
            "Margin": real_margin,
            "ROI %": round(real_roi*100,2),
            "Volume": vol,
            "Buy Limit": buy_limit,
            "Profit per Limit": profit_per_limit,
            "Profit per Hour": profit_per_hour,
            "Confidence": confidence,
            "Image": get_image_url(names.get(item_id, "Unknown"))
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df, df, df, 0

    df = df.sort_values(by="Confidence", ascending=False)
    normal = df[df["Buy"] < HIGH_VALUE_THRESHOLD].head(15)
    high_value = df[df["Buy"] >= HIGH_VALUE_THRESHOLD].head(10)
    speculative = df.sample(min(10, len(df)))
    return normal, high_value, speculative, len(df)

# ---------- UI ----------
st.set_page_config(page_title="OSRS GE Dashboard", layout="centered")
st.title("📊 OSRS GE Trading Dashboard")
mode = st.selectbox("Mode", ["Relaxed", "Safe"])
capital = st.number_input("Available GP", value=10_000_000, step=1_000_000)

prices, volumes, names = fetch_data()
normal, high_value, speculative, total_found = analyze_items(prices, volumes, names, capital, mode)
st.write(f"🔍 Total viable trades found: {total_found}")

# ---------- Watchlist ----------
if "watchlist" not in st.session_state:
    st.session_state.watchlist = []

def render_table(df, table_key):
    st.write(f"<table style='border-collapse: collapse; width:100%;'>", unsafe_allow_html=True)
    st.write("""
    <tr style='border-bottom:1px solid #ccc;'>
        <th>Item</th><th>Buy</th><th>Sell</th><th>Margin</th><th>ROI %</th>
        <th>Volume</th><th>Buy Limit</th><th>Profit/Limit</th><th>Profit/Hour</th>
        <th>Confidence</th><th>Add</th>
    </tr>
    """, unsafe_allow_html=True)

    for idx, row in df.iterrows():
        margin_color = f"rgb({max(0,150-row['Margin'])},{min(150,row['Margin'])},0)" if row['Margin'] >=0 else "red"
        st.write(f"""
        <tr style='border-bottom:1px solid #ddd;'>
            <td>{row['Item']}</td>
            <td style='color:green'>{row['Buy']}</td>
            <td style='color:red'>{row['Sell']}</td>
            <td style='color:{margin_color}'>{row['Margin']}</td>
            <td style='color:#555'>{row['ROI %']}</td>
            <td style='color:#555'>{row['Volume']}</td>
            <td style='color:#555'>{row['Buy Limit']}</td>
            <td style='color:#555'>{row['Profit per Limit']}</td>
            <td style='color:#555'>{row['Profit per Hour']}</td>
            <td style='color:#555'>{row['Confidence']}</td>
            <td style='text-align:center;'>""", unsafe_allow_html=True)
        if st.button("➕", key=f"{table_key}_add_{idx}", help=f"Add {row['Item']} to Watchlist"):
            st.session_state.watchlist.append({
                "Item": row['Item'],
                "Buy": row['Buy'],
                "Sell": row['Sell'],
                "Volume": row['Volume'],
                "Image": row['Image']
            })
        st.write("</td></tr>", unsafe_allow_html=True)
    st.write("</table>", unsafe_allow_html=True)

# --------- Display Tables ----------
st.subheader("🟢 Profitable Flips")
if normal.empty:
    st.write("No trades found.")
else:
    render_table(normal, "normal")

st.subheader("🔵 High Value Trades")
if high_value.empty:
    st.write("No high-value trades currently.")
else:
    render_table(high_value, "high_value")

st.subheader("🟠 Speculative / Underpriced Trades")
if speculative.empty:
    st.write("No speculative trades currently.")
else:
    render_table(speculative, "speculative")

# --------- Display Watchlist ----------
st.subheader("🟣 Watchlist")
for idx, item in enumerate(st.session_state.watchlist):
    cols = st.columns([1,3])
    with cols[0]:
        st.image(item['Image'], width=50)
    with cols[1]:
        st.markdown(f"**{item['Item']}**")
        st.write(f"Buy: {item['Buy']} | Sell: {item['Sell']} | Volume: {item['Volume']}")
        if st.button("❌ Remove", key=f"watch_remove_{idx}"):
            st.session_state.watchlist.pop(idx)
            st.experimental_rerun()
