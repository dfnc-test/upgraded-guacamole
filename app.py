import requests
import pandas as pd

HISTORICAL_URL = "https://prices.runescape.wiki/api/v1/osrs/timeseries?item="
HEADERS = {"User-Agent": "osrs-ge-dashboard (redsnowcp@gmail.com)"}

# Example: let's test the first 10 items from latest prices
prices_res = requests.get("https://prices.runescape.wiki/api/v1/osrs/latest", headers=HEADERS).json()
test_items = list(prices_res["data"].keys())[:10]

for item_id in test_items:
    print(f"\nItem ID: {item_id}")
    try:
        r = requests.get(f"{HISTORICAL_URL}{item_id}", headers=HEADERS, timeout=5)
        if r.status_code != 200:
            print(f"HTTP {r.status_code}")
            continue
        hist_data = r.json().get("data", {})
        print(f"Historical data keys: {list(hist_data.keys())[:5]} (total {len(hist_data)} points)")
        if hist_data:
            prices_list = list(hist_data.values())
            print(f"Sample prices: {prices_list[:5]}")
        else:
            print("No historical data returned")
    except Exception as e:
        print(f"Error: {e}")
