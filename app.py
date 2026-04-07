import streamlit as st
import requests
import pandas as pd

# ---------- CONFIG ----------
LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
HEADERS = {"User-Agent": "osrs-ge-dashboard (redsnowcp@gmail.com)"}

GE_TAX = 0.05
HIGH_VALUE_THRESHOLD = 1_000_000
MIN_VOLUME = 500
MIN_MARGIN = 20
BUY_LIMIT_HOURS = 4

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
    id_to_type = {item["id"]: item.get("type", "") for item in mapping}
    return prices, volumes, id_to_name, id_to_limit, id_to_type

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
        real_margin = real_sell - low
        if real_margin < MIN_MARGIN:
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

def high_volume_flips(prices, volumes, names, types):
    rows=[]
    for item_id, data in prices.items():
        item_id=int(item_id)
        high, low = data.get("high"), data.get("low")
        if not high or not low or low<=0: continue
        vol_data = volumes.get(str(item_id),{})
        volume = vol_data.get("highPriceVolume",0)+vol_data.get("lowPriceVolume",0)
        if volume<2000: continue
        margin=high-low
        if margin>50: continue
        rows.append({
            "Image": get_image_url(names.get(item_id,"Unknown")),
            "Item": names.get(item_id,"Unknown"),
            "Buy": low,
            "Sell": high,
            "Max Price": high,
            "Margin": int(margin),
            "Volume": volume,
            "Type": types.get(item_id,"")
        })
    return pd.DataFrame(rows).sort_values(by="Volume", ascending=False).head(20)

def speculative_trades(prices, volumes, names):
    rows=[]
    for item_id, data in prices.items():
        item_id=int(item_id)
        low = data.get("low")
        high = data.get("high")
        if not low or not high or low <= 0: continue
        vol_data = volumes.get(str(item_id), {})
        volume = vol_data.get("highPriceVolume",0)+vol_data.get("lowPriceVolume",0)
        margin = high - low
        if margin < MIN_MARGIN or volume < MIN_VOLUME: continue
        roi = margin / low
        volume_score = min(volume/100_000,1)
        margin_score = min(margin/1000,1)
        roi_score = min(roi/0.1,1)
        confidence_score = round((volume_score + margin_score + roi_score)/3*100,1)
        rows.append({
            "Image": get_image_url(names.get(item_id,"Unknown")),
            "Item": names.get(item_id,"Unknown"),
            "Buy": low,
            "Sell": high,
            "Margin": int(margin),
            "ROI %": round(roi*100,2),
            "Volume": volume,
            "Confidence": confidence_score
        })
    return pd.DataFrame(rows).sort_values(by="Confidence", ascending=False).head(20)

# ---------- DISPLAY WITH ICONS ----------
def render_table_with_icons(df):
    df = df.copy()
    df["Image"] = df["Image"].apply(lambda url: f'<img src="{url}" width="20" style="vertical-align:middle">')
    # Put Image first
    cols = df.columns.tolist()
    cols.insert(0, cols.pop(cols.index("Image")))
    df = df[cols]
    html_table = df.to_html(escape=False, index=False)
    st.markdown(html_table, unsafe_allow_html=True)

# ---------- UI ----------
st.set_page_config(page_title="OSRS GE Dashboard with Icons", layout="wide")
st.title("📊 OSRS GE Dashboard with Icons")

prices, volumes, names, limits, types = fetch_data()

st.subheader("💰 Regular Profitable Trades")
regular_df = calculate_flips(prices, volumes, names, limits)
if regular_df.empty:
    st.write("No regular trades found.")
else:
    render_table_with_icons(regular_df)

st.subheader("⚡ High Volume / Low Margin Flips")
high_vol_df = high_volume_flips(prices, volumes, names, types)
if high_vol_df.empty:
    st.write("No high-volume flips found.")
else:
    render_table_with_icons(high_vol_df)

st.subheader("🔮 Speculative / Underpriced Trades")
spec_df = speculative_trades(prices, volumes, names)
if spec_df.empty:
    st.write("No speculative trades found.")
else:
    render_table_with_icons(spec_df)
