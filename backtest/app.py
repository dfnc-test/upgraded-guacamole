import streamlit as st
import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import random

# ---------- CONFIG ----------
LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
HEADERS = {"User-Agent": "osrs-ge-backtest (redsnowcp@gmail.com)"}

STARTING_GP = 5_000_000
TRADING_MODELS = ["Z-Score", "High Volume", "Diversified"]
TIMEFRAMES = {"30 Days": 30, "60 Days": 60, "1 Year": 365}
GE_TAX = 0.05

# ---------- HELPERS ----------
def get_image_url(name):
    formatted = name.replace(" ", "_").replace("'", "").replace("(", "").replace(")", "")
    return f"https://oldschool.runescape.wiki/images/{formatted}.png"

@st.cache_data(ttl=3600)
def fetch_prices():
    data = requests.get(LATEST_URL, headers=HEADERS, timeout=10).json()["data"]
    mapping = requests.get(MAPPING_URL, headers=HEADERS, timeout=10).json()
    id_to_name = {item["id"]: item["name"] for item in mapping}
    return data, id_to_name

@st.cache_data(ttl=3600)
def fetch_history(item_id, timeout=30):
    """Fetch historical midpoint prices for backtesting"""
    try:
        url = f"https://prices.runescape.wiki/api/v1/osrs/timeseries?id={item_id}&timestep=1d"
        res = requests.get(url, headers=HEADERS, timeout=timeout).json()
        data = res.get("data", [])
        if not isinstance(data, list) or len(data) == 0:
            return None
        prices = []
        for point in data:
            high = point.get("avgHighPrice", 0)
            low = point.get("avgLowPrice")
            if high and low is not None:
                prices.append((high + low)/2)
            elif high:
                prices.append(high)
        if len(prices) < 3:
            return None
        return prices
    except:
        return None

def simulate_trades(item_prices, model, cash, holdings):
    """Decide trades based on model indicators"""
    trades = []
    for item_id, history in item_prices.items():
        if history is None or len(history) < 3:
            continue
        current_price = history[-1]
        mean = np.mean(history)
        std = np.std(history, ddof=0)
        z = (current_price - mean)/std if std>0 else 0

        # Model strategies
        if model == "Z-Score" and z < -0.5:
            trades.append((item_id, current_price))
        elif model == "High Volume" and current_price > 50:  # simple placeholder for high volume
            trades.append((item_id, current_price))
        elif model == "Diversified" and (z < -0.3 or current_price > 50):
            trades.append((item_id, current_price))

    # Execute trades
    for item_id, price in trades:
        qty = int(cash / (len(trades) * price)) if trades else 0
        if qty > 0:
            holdings[item_id] = holdings.get(item_id, 0) + qty
            cash -= qty * price
    return cash, holdings

def calculate_portfolio_value(holdings, current_prices, cash):
    value = cash
    for item_id, qty in holdings.items():
        value += qty * current_prices.get(item_id, 0)
    return value

# ---------- MAIN ----------
st.title("📈 OSRS GE Backtest Simulator")
st.write("Simulates 3 trading models over 30/60/365 days using historical GE data.")

# Fetch data
st.info("Fetching latest GE data...")
prices, names = fetch_prices()

# Pick top 100 items by high price as candidates
top_items = dict(sorted(prices.items(), key=lambda x: x[1].get("high",0), reverse=True)[:100])

# Fetch historical data
st.info("Fetching historical data (this may take a minute)...")
item_histories = {}
for item_id in top_items.keys():
    hist = fetch_history(int(item_id))
    if hist:
        item_histories[int(item_id)] = hist

# Run backtests
results = {tf: {model: [] for model in TRADING_MODELS} for tf in TIMEFRAMES}

for tf_name, days in TIMEFRAMES.items():
    st.info(f"Simulating {tf_name}...")
    for model in TRADING_MODELS:
        cash = STARTING_GP
        holdings = {}
        portfolio_values = []
        for day in range(days):
            # Collect current prices for this day
            current_prices = {item_id: hist[min(day, len(hist)-1)] for item_id, hist in item_histories.items()}
            # Decide trades
            cash, holdings = simulate_trades(item_histories, model, cash, holdings)
            # Portfolio value
            portfolio_values.append(calculate_portfolio_value(holdings, current_prices, cash))
        results[tf_name][model] = portfolio_values

# ---------- DISPLAY ----------
st.subheader("📊 Portfolio Performance")
for tf_name, days in TIMEFRAMES.items():
    st.write(f"### {tf_name}")
    plt.figure(figsize=(12,5))
    for model in TRADING_MODELS:
        plt.plot(results[tf_name][model], label=model)
    plt.xlabel("Days")
    plt.ylabel("Portfolio Value (GP)")
    plt.title(f"{tf_name} Performance")
    plt.legend()
    st.pyplot(plt.gcf())
    plt.clf()

# Summary Table
st.subheader("💰 Portfolio Summary")
summary_data = []
for tf_name in TIMEFRAMES.keys():
    for model in TRADING_MODELS:
        final_value = results[tf_name][model][-1] if results[tf_name][model] else STARTING_GP
        summary_data.append({"Timeframe": tf_name, "Model": model, "Final GP": int(final_value)})

df_summary = pd.DataFrame(summary_data)
st.dataframe(df_summary)
