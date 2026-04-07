import streamlit as st
import requests
import pandas as pd

# ---------- CONFIG ----------
LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"
VOLUME_URL = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# ---------- FETCH ----------
@st.cache_data(ttl=60)
def fetch_data():
    try:
        prices_res = requests.get(LATEST_URL, headers=HEADERS, timeout=10)
        volumes_res = requests.get(VOLUME_URL, headers=HEADERS, timeout=10)
        mapping_res = requests.get(MAPPING_URL, headers=HEADERS, timeout=10)

        st.write("Status:", prices_res.status_code, volumes_res.status_code)

        prices_json = prices_res.json()
        volumes_json = volumes_res.json()
        mapping_json = mapping_res.json()

        prices = prices_json.get("data", {})
        volumes = volumes_json.get("data", {})

        st.write("Prices count:", len(prices))
        st.write("Volumes count:", len(volumes))

        id_to_name = {item["id"]: item["name"] for item in mapping_json}

        return prices, volumes, id_to_name

    except Exception as e:
        st.error(f"Fetch error: {e}")
        return {}, {}, {}


# ---------- ANALYZE ----------
def analyze_items(prices, volumes, names):
    rows = []

    for item_id, data in prices.items():
        item_id = int(item_id)

        high = data.get("high")
        low = data.get("low")

        if not high or not low or low == 0:
            continue

        vol_data = volumes.get(str(item_id), {})

        # ✅ Correct volume
        volume = (
            vol_data.get("highPriceVolume", 0) +
            vol_data.get("lowPriceVolume", 0)
        )

        if volume <= 0:
            continue

        margin = high - low

        if margin <= 0:
            continue

        rows.append({
            "Item": names.get(item_id, "Unknown"),
            "Buy": low,
            "Sell": high,
            "Margin": margin,
            "Volume": volume
        })

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    return df.sort_values(by="Volume", ascending=False).head(20)


# ---------- UI ----------
st.set_page_config(page_title="OSRS Debug", layout="centered")
st.title("🛠️ OSRS GE Debug Dashboard")

prices, volumes, names = fetch_data()

if not prices:
    st.error("No price data — API likely failed")
elif not volumes:
    st.error("No volume data — API likely failed")
else:
    df = analyze_items(prices, volumes, names)

    if df.empty:
        st.warning("No items passed filters — showing raw sample instead")

        # 🔥 Fallback: show raw data so page is NEVER blank
        sample = list(prices.items())[:10]
        st.write(sample)
    else:
        st.dataframe(df)
