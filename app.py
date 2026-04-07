import streamlit as st
import requests
import pandas as pd
import numpy as np
import json
import os

# ---------- CONFIG ----------
LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
HISTORY_URL = "https://prices.runescape.wiki/api/v1/osrs/market/{item_id}/daily"
HEADERS = {"User-Agent": "osrs-ge-dashboard (redsnowcp@gmail.com)"}

GE_TAX = 0.05
MIN_VOLUME = 500
MIN_MARGIN = 20
BUY_LIMIT_HOURS = 4
WATCHLIST_FILE = "watchlist.json"
SMA_PERIOD = 7  # 7-day SMA
EMA_PERIOD = 7  # 7-day EMA
MOMENTUM_PERIOD = 3  # rate of change over 3 periods

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

def fetch_history(item_id):
    try:
        data = requests.get(HISTORY_URL.format(item_id=item_id), headers=HEADERS, timeout=10).json()
        history = pd.DataFrame(data.get("daily", []))
        if not history.empty:
            history['price'] = history['average']
        return history
    except:
        return pd.DataFrame()

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

        # Historical analysis
        hist = fetch_history(item_id)
        if not hist.empty:
            hist['SMA'] = hist['price'].rolling(SMA_PERIOD).mean()
            hist['EMA'] = hist['price'].ewm(span=EMA_PERIOD, adjust=False).mean()
            hist['Momentum'] = hist['price'].pct_change(periods=MOMENTUM_PERIOD)
            mean = hist['price'].mean()
            std = hist['price'].std() if hist['price'].std() > 0 else 1
            z_score = (hist['price'].iloc[-1] - mean)/std
            vol_avg = hist['volume'].rolling(SMA_PERIOD).mean().iloc[-1] if 'volume' in hist.columns else 1
            volume_spike = volume / max(vol_avg, 1)
            high_7d = hist['price'].tail(7).max()
            low_7d = hist['price'].tail(7).min()
        else:
            hist = pd.DataFrame()
            z_score = 0
            volume_spike = 1
            high_7d = high
            low_7d = low
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
            "Confidence": confidence_score,
            "SMA": round(hist['SMA'].iloc[-1],2) if not hist.empty else 0,
            "EMA": round(hist['EMA'].iloc[-1],2) if not hist.empty else 0,
            "Momentum": round(hist['Momentum'].iloc[-1]*100,2) if not hist.empty else 0,
            "Z-Score": round(z_score,2),
            "Volume Spike": round(volume_spike,2),
            "7d High": high_7d,
            "7d Low": low_7d
        })
    return pd.DataFrame(rows).sort_values(by="Profit per Hour", ascending=False).head(20)

# ---------- DISPLAY ----------
def render_table(df, table_key):
    df = df.copy()
    df["Image"] = df["Image"].apply(lambda url: f'<img src="{url}" width="20" style="vertical-align:middle">')
    # Add hover descriptions
    headers_hover = {
        "SMA": "Simple Moving Average over 7 days",
        "EMA": "Exponential Moving Average over 7 days",
        "Momentum": "Price % change over last 3 periods",
        "Z-Score": "How far current price is from mean in std deviations",
        "Volume Spike": "Current volume / 7-day average volume",
        "7d High": "Highest price in last 7 days",
        "7d Low": "Lowest price in last 7 days"
    }
    def render_header_with_hover(col):
        if col in headers_hover:
            return f'<th title="{headers_hover[col]}">{col}</th>'
        return f'<th>{col}</th>'
    # Build table HTML
    table_html = "<table border='1' style='border-collapse:collapse; text-align:center;'>"
    table_html += "<tr>" + "".join([render_header_with_hover(c) for c in df.columns]) + "</tr>"
    for _, row in df.iterrows():
        table_html += "<tr>" + "".join([f"<td>{row[c]}</td>" for c in df.columns]) + "</tr>"
    table_html += "</table>"
    st.markdown(table_html, unsafe_allow_html=True)

# ---------- MAIN ----------
st.set_page_config(page_title="OSRS GE Dashboard with Indicators", layout="wide")
st.title("📊 OSRS GE Dashboard with Technical Indicators")

prices, volumes, names, limits = fetch_data()
df_trades = calculate_flips(prices, volumes, names, limits)
if df_trades.empty:
    st.write("No trades found.")
else:
    render_table(df_trades, "main_trades")
