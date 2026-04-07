import streamlit as st
import requests
import pandas as pd
import numpy as np

# ---------- CONFIG ----------
LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
HISTORICAL_URL = "https://prices.runescape.wiki/api/v1/osrs/timeseries?item="
HEADERS = {"User-Agent": "osrs-ge-dashboard (redsnowcp@gmail.com)"}

MIN_VOLUME = 1000
MIN_MARGIN = 20
GE_TAX = 0.05
BUY_LIMIT_HOURS = 4
SPEC_LOOKBACK_DAYS = 30
SPEC_UNDERPRICED_PCT = 0.85  # 15% below historical average

# ---------- FETCH ----------
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
        volume_score = min(volume / 100_000,1)
        margin_score = min(real_margin / 1000,1)
        roi_score = min(roi / 0.1,1)
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
            "Item ID": item_id
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
            "Type": types.get(item_id,"")
        })
    df=pd.DataFrame(rows)
    if df.empty: return df
    return df.sort_values(by="Volume", ascending=False).head(20)

def speculative_trades(prices, volumes, names, min_days=3, underpriced_pct=0.85):
    rows = []
    for item_id, data in prices.items():
        item_id = int(item_id)
        low = data.get("low")
        if not low or low <= 0:
            continue
        try:
            hist_res = requests.get(f"{HISTORICAL_URL}{item_id}", headers=HEADERS, timeout=5)
            hist_data = hist_res.json().get("data", {})
            if not hist_data or len(hist_data) < min_days:
                continue
            # take the last N days available
            prices_list = list(hist_data.values())[-min_days:]
            avg_price = np.mean(prices_list)
            if low < avg_price * underpriced_pct:
                volume = volumes.get(str(item_id), {}).get("highPriceVolume",0) + volumes.get(str(item_id), {}).get("lowPriceVolume",0)
                margin = avg_price - low
                confidence_score = round(min(volume/100_000,1)*0.5 + min(margin/1000,1)*0.5*100,1)
                rows.append({
                    "Item": names.get(item_id,"Unknown"),
                    "Current Low": low,
                    "Historical Avg": int(avg_price),
                    "Potential Margin": int(margin),
                    "Volume": volume,
                    "Confidence": confidence_score
                })
        except:
            continue
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["Item","Current Low","Historical Avg","Potential Margin","Volume","Confidence"])
    return df.sort_values(by="Confidence", ascending=False).head(20)

# ---------- UI ----------
st.set_page_config(page_title="OSRS GE Dashboard v2", layout="centered")
st.title("📊 OSRS GE Advanced Dashboard with Speculative Confidence")

prices, volumes, names, limits, types = fetch_data()

st.subheader("💰 Regular Profitable Trades")
regular_df = calculate_flips(prices, volumes, names, limits)
st.dataframe(regular_df if not regular_df.empty else pd.DataFrame({"Info":["No trades found"]}))

st.subheader("⚡ High Volume / Low Margin Flips")
high_vol_df = high_volume_flips(prices, volumes, names, types)
st.dataframe(high_vol_df if not high_vol_df.empty else pd.DataFrame({"Info":["No trades found"]}))

st.subheader("🔮 Speculative / Underpriced Trades")
spec_df = speculative_trades(prices, volumes, names)
st.dataframe(spec_df if not spec_df.empty else pd.DataFrame({"Info":["No speculative trades found"]}))
