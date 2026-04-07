import streamlit as st
import requests
import pandas as pd
import numpy as np

# ---------- CONFIG ----------
LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
HEADERS = {"User-Agent": "osrs-ge-dashboard (redsnowcp@gmail.com)"}

STOP_LOSS_PCT = 0.03
TAKE_PROFIT_PCT = 0.05
GE_TAX = 0.05
HIGH_VALUE_THRESHOLD = 1_000_000

MIN_VOLUME = 500  # min volume for speculative / flips
MIN_MARGIN = 20   # min margin for speculative flips

BUY_LIMIT_HOURS = 4  # 4 hours typical buy limit period

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
    prices_res = requests.get(LATEST_URL, headers=HEADERS, timeout=10)
    volumes_res = requests.get(VOLUME_URL, headers=HEADERS, timeout=10)
    mapping_res = requests.get(MAPPING_URL, headers=HEADERS, timeout=10)

    prices = prices_res.json()["data"]
    volumes = volumes_res.json()["data"]
    mapping = mapping_res.json()

    id_to_name = {item["id"]: item["name"] for item in mapping}
    id_to_limit = {item["id"]: item.get("limit", 0) for item in mapping}
    id_to_type = {item["id"]: item.get("type", "") for item in mapping}

    return prices, volumes, id_to_name, id_to_limit, id_to_type

# ---------- REGULAR FLIPS ----------
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
        # Confidence score
        volume_score = min(volume / 100_000, 1)
        margin_score = min(real_margin / 1000, 1)
        roi_score = min(roi / 0.1, 1)
        confidence_score = round((volume_score + margin_score + roi_score)/3*100,1)
        rows.append({
            "Item": names.get(item_id,"Unknown"),
            "Buy": low,
            "Sell": int(real_sell),
            "Margin": int(real_margin),
            "ROI %": round(roi*100,2),
            "Volume": volume,
            "Buy Limit": buy_limit,
            "Profit per Limit": int(profit_per_limit),
            "Profit per Hour": int(profit_per_hour),
            "Confidence": confidence_score,
            "Image": get_image_url(names.get(item_id,"Unknown"))
        })
    df = pd.DataFrame(rows)
    if df.empty: return df
    return df.sort_values(by="Profit per Hour", ascending=False).head(20)

# ---------- HIGH VOLUME / LOW MARGIN ----------
def high_volume_flips(prices, volumes, names, types, min_volume=2000, max_margin=50):
    rows=[]
    for item_id, data in prices.items():
        item_id=int(item_id)
        high, low = data.get("high"), data.get("low")
        if not high or not low or low<=0: continue
        vol_data = volumes.get(str(item_id),{})
        volume = vol_data.get("highPriceVolume",0)+vol_data.get("lowPriceVolume",0)
        if volume<min_volume: continue
        margin=high-low
        if margin>max_margin: continue
        rows.append({
            "Item": names.get(item_id,"Unknown"),
            "Buy": low,
            "Sell": high,
            "Margin": int(margin),
            "Volume": volume,
            "Type": types.get(item_id,""),
            "Image": get_image_url(names.get(item_id,"Unknown"))
        })
    df=pd.DataFrame(rows)
    if df.empty: return df
    return df.sort_values(by="Volume", ascending=False).head(20)

# ---------- SPECULATIVE TRADES ----------
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
        # confidence = combination of volume, margin, ROI
        volume_score = min(volume/100_000,1)
        margin_score = min(margin/1000,1)
        roi_score = min(roi/0.1,1)
        confidence_score = round((volume_score + margin_score + roi_score)/3*100,1)
        rows.append({
            "Item": names.get(item_id,"Unknown"),
            "Buy": low,
            "Sell": high,
            "Margin": int(margin),
            "ROI %": round(roi*100,2),
            "Volume": volume,
            "Confidence": confidence_score,
            "Image": get_image_url(names.get(item_id,"Unknown"))
        })
    df=pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["Item","Buy","Sell","Margin","ROI %","Volume","Confidence","Image"])
    return df.sort_values(by="Confidence", ascending=False).head(20)

# ---------- UI ----------
st.set_page_config(page_title="OSRS GE Dashboard v3", layout="centered")
st.title("📊 OSRS GE Advanced Dashboard v3")

prices, volumes, names, limits, types = fetch_data()

# Regular flips
st.subheader("💰 Regular Profitable Trades")
regular_df = calculate_flips(prices, volumes, names, limits)
if regular_df.empty:
    st.write("No regular trades found.")
else:
    for _, row in regular_df.iterrows():
        cols = st.columns([1, 3])
        with cols[0]: st.image(row["Image"], width=50)
        with cols[1]:
            st.markdown(f"**{row['Item']}**")
            st.write(f"Buy: {row['Buy']} | Sell: {row['Sell']} | Margin: {row['Margin']}")
            st.write(f"ROI: {row['ROI %']}% | Volume: {row['Volume']} | Buy Limit: {row['Buy Limit']}")
            st.write(f"Profit/Limit: {row['Profit per Limit']} | Profit/Hr: {row['Profit per Hour']}")
            st.write(f"Confidence: {row['Confidence']}")

# High volume / low margin
st.subheader("⚡ High Volume / Low Margin Flips")
high_vol_df = high_volume_flips(prices, volumes, names, types)
if high_vol_df.empty:
    st.write("No high-volume flips found.")
else:
    for _, row in high_vol_df.iterrows():
        cols = st.columns([1,3])
        with cols[0]: st.image(row["Image"], width=50)
        with cols[1]:
            st.markdown(f"**{row['Item']}**")
            st.write(f"Buy: {row['Buy']} | Sell: {row['Sell']} | Margin: {row['Margin']} | Volume: {row['Volume']}")

# Speculative trades
st.subheader("🔮 Speculative / Underpriced Trades")
spec_df = speculative_trades(prices, volumes, names)
if spec_df.empty:
    st.write("No speculative trades found.")
else:
    for _, row in spec_df.iterrows():
        cols = st.columns([1,3])
        with cols[0]: st.image(row["Image"], width=50)
        with cols[1]:
            st.markdown(f"**{row['Item']}**")
            st.write(f"Buy: {row['Buy']} | Sell: {row['Sell']} | Margin: {row['Margin']} | ROI: {row['ROI %']}% | Volume: {row['Volume']}")
            st.write(f"Confidence: {row['Confidence']}")
