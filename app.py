import streamlit as st
import requests
import pandas as pd
import numpy as np
import json
import os
import random

# ---------- CONFIG ----------
LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"

HEADERS = {"User-Agent": "osrs-ge-dashboard (redsnowcp@gmail.com)"}

GE_TAX = 0.05
MIN_VOLUME = 500
HIGH_VOLUME_THRESHOLD = 50_000
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

# ---------- HISTORICAL DATA ----------
@st.cache_data(ttl=3600)
def fetch_history(item_id, timeout=30):
    """Fetch historical midpoint prices for Z-score calculation"""
    try:
        url = f"https://prices.runescape.wiki/api/v1/osrs/timeseries?id={item_id}&timestep=1h"
        res = requests.get(url, headers=HEADERS, timeout=timeout).json()
        data = res.get("data", [])
        if not isinstance(data, list) or len(data) == 0:
            st.write(f"No historical data returned for item {item_id}")
            return None

        prices = []
        for point in data:
            high = point.get("avgHighPrice", 0)
            low = point.get("avgLowPrice")
            if high and low is not None:
                prices.append((high + low) / 2)
            elif high:
                prices.append(high)

        if len(prices) < 3:
            return None
        return pd.Series(prices)
    except Exception as e:
        st.write(f"Error fetching history for {item_id}: {e}")
        return None

# ---------- DEBUGGING Z-SCORE ----------
st.subheader("🛠️ Debug Z-Score for Random Item")
prices, volumes, names, limits = fetch_data()

random_item_id = int(random.choice(list(prices.keys())))
random_item_data = prices[str(random_item_id)]
high, low = random_item_data.get("high"), random_item_data.get("low")
mid_price = (high + low) / 2 if high and low else None

if mid_price:
    hist = fetch_history(random_item_id)
    if hist is not None:
        hist_mean = hist.mean()
        hist_std = hist.std(ddof=0)
        z = (mid_price - hist_mean) / hist_std if hist_std > 0 else 0.0
        debug_df = pd.DataFrame({
            "MidPrice": hist.values
        })
        st.write(f"Random Item: {random_item_id} - {high}/{low} (Mid={mid_price})")
        st.write(f"Historical Mean: {hist_mean:.2f}, Std: {hist_std:.2f}, Z-score: {z:.2f}")
        st.dataframe(debug_df)
    else:
        st.write(f"No historical data returned for item {random_item_id}")
else:
    st.write(f"Random item {random_item_id} has invalid high/low prices.")
