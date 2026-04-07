# backtest/app.py
import streamlit as st
import requests
import pandas as pd
import numpy as np
import json
import os
import datetime
import matplotlib.pyplot as plt

# ---------- CONFIG ----------
LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
HEADERS = {"User-Agent": "osrs-ge-backtest (redsnowcp@gmail.com)"}

GE_TAX = 0.05
START_GOLD = 5_000_000
NUM_ITEMS = 100  # number of items to backtest
WATCHLIST_FILE = "../watchlist.json"

# ---------- HELPERS ----------
def get_image_url(name):
    formatted = name.replace(" ", "_").replace("'", "").replace("(", "").replace(")", "")
    return f"https://oldschool.runescape.wiki/images/{formatted}.png"

@st.cache_data(ttl=3600)
def fetch_prices():
    latest = requests.get(LATEST_URL, headers=HEADERS, timeout=15).json()["data"]
    mapping = requests.get(MAPPING_URL, headers=HEADERS, timeout=15).json()
    id_to_name = {item["id"]: item["name"] for item in mapping}
    id_to_limit = {item["id"]: item.get("limit", 0) for item in mapping}
    return latest, id_to_name, id_to_limit

@st.cache_data(ttl=3600)
def fetch_history(item_id, days=365, timestep="1d", timeout=30):
    """Fetch historical prices for the last `days` days"""
    try:
        url = f"https://prices.runescape.wiki/api/v1/osrs/timeseries?id={item_id}&timestep={timestep}"
        res = requests.get(url, headers=HEADERS, timeout=timeout).json()
        data = res.get("data", [])
        if not isinstance(data, list) or len(data) == 0:
            return None

        prices = []
        now = int(datetime.datetime.utcnow().timestamp())
        cutoff = now - days * 86400

        for point in data:
            ts = point.get("timestamp")
            if ts is None or ts < cutoff:
                continue
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

# ---------- PORTFOLIO SIMULATION ----------
def compute_indicators(prices_series):
    """Compute indicators for Z-score, momentum, SMA, EMA"""
    mid = prices_series.iloc[-1]
    sma = prices_series.mean()
    ema = prices_series.ewm(span=5).mean().iloc[-1]
    momentum = ((prices_series.iloc[-1] - prices_series.iloc[-2]) / prices_series.iloc[-2])*100 if len(prices_series)>1 else 0
    z = (mid - sma)/prices_series.std(ddof=0) if prices_series.std(ddof=0) > 0 else 0
    return mid, sma, ema, momentum, z

def simulate_portfolio(latest, names, limits, items, days):
    portfolio = {"cash": START_GOLD, "holdings": {}, "history": []}
    equity_curve = []
    for day in range(days):
        # Simulate each item
        for item_id in items:
            hist = fetch_history(item_id, days=days)
            if hist is None or len(hist)<3:
                continue
            mid, sma, ema, momentum, z = compute_indicators(hist)
            # Simple strategy: BUY if Z < -0.5, SELL if Z > 0.5
            if z < -0.5 and portfolio["cash"] >= mid:
                qty = int(portfolio["cash"] // mid)
                portfolio["holdings"][item_id] = portfolio["holdings"].get(item_id,0) + qty
                portfolio["cash"] -= qty * mid
            elif z > 0.5 and item_id in portfolio["holdings"]:
                qty = portfolio["holdings"].pop(item_id)
                portfolio["cash"] += qty * mid
        # Calculate total equity
        total = portfolio["cash"]
        for item_id, qty in portfolio["holdings"].items():
            price = latest.get(str(item_id), {}).get("high") or latest.get(str(item_id), {}).get("low") or 0
            total += price*qty
        equity_curve.append(total)
    return equity_curve

# ---------- MAIN ----------
st.set_page_config(layout="wide")
st.title("🤖 OSRS GE Backtest Simulator")

st.write(f"Simulating {NUM_ITEMS} items, starting with {START_GOLD} gp per portfolio.")

latest, names, limits = fetch_prices()
all_items = list(latest.keys())[:NUM_ITEMS]

timeframes = [30, 60, 365]
results = {}

for days in timeframes:
    st.subheader(f"⏱ Backtest over last {days} days")
    equity_curve = simulate_portfolio(latest, names, limits, all_items, days)
    results[days] = equity_curve
    # Plot equity curve
    plt.figure(figsize=(10,4))
    plt.plot(equity_curve, label=f"Equity over {days} days")
    plt.ylabel("Total GP")
    plt.xlabel("Simulation step")
    plt.legend()
    st.pyplot(plt)

st.success("Backtest complete. Portfolios simulated using Z-score and momentum indicators.")
