import streamlit as st
import requests

HISTORICAL_URL = "https://prices.runescape.wiki/api/v1/osrs/timeseries?item="
HEADERS = {"User-Agent": "osrs-ge-dashboard (redsnowcp@gmail.com)"}

st.title("🛠 Debug OSRS Speculative Trades")

# Fetch first 10 items from latest prices
prices_res = requests.get("https://prices.runescape.wiki/api/v1/osrs/latest", headers=HEADERS).json()
test_items = list(prices_res["data"].keys())[:10]

for item_id in test_items:
    st.subheader(f"Item ID: {item_id}")
    try:
        r = requests.get(f"{HISTORICAL_URL}{item_id}", headers=HEADERS, timeout=5)
        st.text(f"HTTP status: {r.status_code}")
        hist_data = r.json().get("data", {})
        if hist_data:
            st.text(f"Number of data points: {len(hist_data)}")
            sample_prices = list(hist_data.values())[:5]
            st.text(f"Sample prices: {sample_prices}")
        else:
            st.text("No historical data returned")
    except Exception as e:
        st.text(f"Error: {e}")
