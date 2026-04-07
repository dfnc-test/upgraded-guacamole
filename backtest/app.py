import streamlit as st
import requests
import pandas as pd
import numpy as np

# ---------- CONFIG ----------
LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
HEADERS = {"User-Agent": "osrs-ge-backtest (youremail@example.com)"}

GE_TAX = 0.05
HIST_TIMESTEP = "1h"  # hourly data for backtest
BUY_LIMIT_DEFAULT = 100

# ---------- HELPERS ----------
def get_image_url(name):
    formatted = name.replace(" ", "_").replace("'", "").replace("(", "").replace(")", "")
    return f"https://oldschool.runescape.wiki/images/{formatted}.png"

@st.cache_data(ttl=3600)
def fetch_mapping():
    mapping = requests.get(MAPPING_URL, headers=HEADERS, timeout=10).json()
    id_to_name = {item["id"]: item["name"] for item in mapping}
    id_to_limit = {item["id"]: item.get("limit", BUY_LIMIT_DEFAULT) for item in mapping}
    return id_to_name, id_to_limit

@st.cache_data(ttl=3600)
def fetch_history(item_id, timeout=30):
    """Fetch historical hourly midpoint prices"""
    try:
        url = f"https://prices.runescape.wiki/api/v1/osrs/timeseries?id={item_id}&timestep={HIST_TIMESTEP}"
        res = requests.get(url, headers=HEADERS, timeout=timeout).json()
        data = res.get("data", [])
        if not isinstance(data, list) or len(data) < 3:
            return None

        prices = []
        timestamps = []
        for point in data:
            high = point.get("avgHighPrice", 0)
            low = point.get("avgLowPrice")
            ts = point.get("timestamp")
            if high and low is not None:
                prices.append((high + low) / 2)
                timestamps.append(ts)
            elif high:
                prices.append(high)
                timestamps.append(ts)

        return pd.DataFrame({"timestamp": timestamps, "mid": prices})
    except Exception as e:
        st.write(f"Error fetching history for {item_id}: {e}")
        return None

# ---------- INDICATORS ----------
def calculate_indicators(df):
    df = df.copy()
    df["SMA"] = df["mid"].rolling(5).mean()
    df["EMA"] = df["mid"].ewm(span=5, adjust=False).mean()
    df["Momentum"] = df["mid"].pct_change() * 100
    df["Z"] = (df["mid"] - df["mid"].rolling(20).mean()) / df["mid"].rolling(20).std(ddof=0)
    df["BuySignal"] = df["Z"] < -0.5
    df["SellSignal"] = df["Z"] > 0.5
    return df

# ---------- TRADE SIMULATION ----------
def simulate_trades(df, buy_limit=BUY_LIMIT_DEFAULT):
    cash = 0
    inventory = 0
    trades = []
    
    for i, row in df.iterrows():
        price = row["mid"]
        if row["BuySignal"] and cash == 0:
            # Buy max allowed
            inventory = buy_limit
            cost = inventory * price
            cash -= cost
            trades.append({"timestamp": row["timestamp"], "action": "BUY", "price": price, "qty": inventory, "cash": cash})
        elif row["SellSignal"] and inventory > 0:
            # Sell all
            revenue = inventory * price * (1 - GE_TAX)
            cash += revenue
            trades.append({"timestamp": row["timestamp"], "action": "SELL", "price": price, "qty": inventory, "cash": cash})
            inventory = 0
    # Final liquidation
    if inventory > 0:
        cash += inventory * df.iloc[-1]["mid"] * (1 - GE_TAX)
        trades.append({"timestamp": df.iloc[-1]["timestamp"], "action": "FINAL_SELL", "price": df.iloc[-1]["mid"], "qty": inventory, "cash": cash})
        inventory = 0

    total_profit = cash
    return trades, total_profit

# ---------- STREAMLIT UI ----------
st.set_page_config(layout="wide")
st.title("📊 OSRS GE Backtest Simulator with Trade Simulation")

id_to_name, id_to_limit = fetch_mapping()
item_ids = list(id_to_name.keys())
item_name_list = [f"{v} ({k})" for k, v in id_to_name.items()]

selected_item = st.selectbox("Select an item to backtest", item_name_list)
item_id = int(selected_item.split("(")[-1].replace(")", ""))
buy_limit = id_to_limit.get(item_id, BUY_LIMIT_DEFAULT)

st.write(f"Fetching historical data for **{id_to_name[item_id]}**...")
hist_df = fetch_history(item_id)

if hist_df is not None:
    hist_df = calculate_indicators(hist_df)
    trades, total_profit = simulate_trades(hist_df, buy_limit=buy_limit)

    st.subheader("💹 Trade Simulation Results")
    st.write(f"Total Profit: {total_profit:.2f} gp over {len(hist_df)} hours")
    
    if trades:
        trades_df = pd.DataFrame(trades)
        trades_df["datetime"] = pd.to_datetime(trades_df["timestamp"], unit="s")
        st.dataframe(trades_df[["datetime", "action", "price", "qty", "cash"]])

    st.subheader("📈 Price and Signals Chart")
    st.line_chart(hist_df[["mid", "SMA", "EMA"]])
    st.bar_chart(hist_df[["BuySignal", "SellSignal"]].astype(int))
else:
    st.write("No historical data available for this item.")
