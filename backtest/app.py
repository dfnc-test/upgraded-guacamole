import streamlit as st
import requests
import pandas as pd
import numpy as np
import random
import matplotlib.pyplot as plt

# ---------- CONFIG ----------
LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"

HEADERS = {"User-Agent": "osrs-ge-dashboard (redsnowcp@gmail.com)"}

GE_TAX = 0.05
MIN_VOLUME = 500
BUY_LIMIT_HOURS = 4
START_GP = 5_000_000
MAX_ITEMS = 100  # max items to backtest

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

@st.cache_data(ttl=3600)
def fetch_history(item_id, timeout=30):
    """Fetch historical midpoint prices for backtesting"""
    try:
        url = f"https://prices.runescape.wiki/api/v1/osrs/timeseries?id={item_id}&timestep=1h"
        res = requests.get(url, headers=HEADERS, timeout=timeout).json()
        data = res.get("data", [])
        if not data or not isinstance(data, list):
            return None
        prices = []
        for point in data:
            high = point.get("avgHighPrice")
            low = point.get("avgLowPrice")
            if high and low is not None:
                prices.append((high + low)/2)
            elif high:
                prices.append(high)
        return pd.Series(prices) if len(prices) >= 7 else None
    except Exception as e:
        st.write(f"Error fetching history for {item_id}: {e}")
        return None

# ---------- BACKTEST ----------
def simulate_portfolio(items, model_name, days, start_gp=START_GP):
    """Simulate trades for one model over given days"""
    portfolio = {"cash": start_gp, "holdings": {}}
    timeline = []

    # Safe backtest loop
for t in range(days):
    buy_candidates = []
    for item_id, hist in items.items():
        if t >= len(hist):
            continue
        current_price = hist.iloc[t]

        if t < 1 or len(hist[:t+1]) < 2:
            margin = 0
            roi = 0
        else:
            prev_price = hist.iloc[t-1]
            margin = current_price - prev_price
            roi = margin / prev_price if prev_price != 0 else 0

        hist_slice = hist[:t+1]
        hist_mean = hist_slice.mean()
        hist_std = hist_slice.std(ddof=0) if hist_slice.std(ddof=0) > 0 else 1
        z = (current_price - hist_mean) / hist_std

        buy = False
        sell = False
        if model_name == "Z-score":
            if z < -0.5: buy = True
            if z > 0.5: sell = True
        elif model_name == "High Margin":
            if margin > 20: buy = True
            if roi > 0.1: sell = True
        elif model_name == "Combined":
            score = z + roi + margin/50
            if score > 0.5: buy = True
            if score < -0.5: sell = True

        # prioritize sell first
        if item_id in portfolio["holdings"] and sell:
            qty = portfolio["holdings"].pop(item_id)
            portfolio["cash"] += qty * current_price * (1-GE_TAX)

        # queue buy candidates
        if buy:
            buy_candidates.append((item_id, current_price))

        # record total value
        total_value = portfolio["cash"]
        for item_id, qty in portfolio["holdings"].items():
            price = items[item_id].iloc[t]
            total_value += qty * price
        timeline.append(total_value)

    return timeline[-1], timeline  # final value, timeline

# ---------- MAIN ----------
st.set_page_config(layout="wide")
st.title("📊 OSRS GE Backtest Simulator")

prices, volumes, names, limits = fetch_data()

# pick top MAX_ITEMS items by volume
sorted_items = sorted(prices.keys(), key=lambda x: volumes.get(str(x), {}).get("highPriceVolume",0)+volumes.get(str(x), {}).get("lowPriceVolume",0), reverse=True)[:MAX_ITEMS]

# fetch historical data
st.info("Fetching historical data (may take some time)...")
items_hist = {}
for i, item_id in enumerate(sorted_items):
    hist = fetch_history(int(item_id))
    if hist is not None:
        items_hist[int(item_id)] = hist
st.success(f"Fetched history for {len(items_hist)} items")

models = ["Z-score","High Margin","Combined"]
timeframes = {"30d":30*24,"60d":60*24,"365d":365*24}  # in hours
results = {}

for model in models:
    results[model] = {}
    for label, days in timeframes.items():
        final_value, timeline = simulate_portfolio(items_hist, model, min(days, max(len(h) for h in items_hist.values())))
        results[model][label] = final_value

# ---------- DISPLAY TABLE ----------
df_results = pd.DataFrame(results).T[["30d","60d","365d"]]
st.subheader("📊 Portfolio Performance Table (GP)")
st.dataframe(df_results.style.format("{:,.0f}"))

# ---------- DISPLAY GRAPHS ----------
st.subheader("📈 Portfolio Performance Over Time")
fig, ax = plt.subplots(figsize=(10,5))
for model in models:
    _, timeline = simulate_portfolio(items_hist, model, max(timeframes.values()))
    ax.plot(timeline, label=model)
ax.set_xlabel("Hours")
ax.set_ylabel("Total GP")
ax.legend()
st.pyplot(fig)
