import requests
import streamlit as st
from config import *

@st.cache_data(ttl=60)
def fetch_data():
    prices = requests.get(LATEST_URL, headers=HEADERS).json()["data"]
    volumes = requests.get(VOLUME_URL, headers=HEADERS).json()["data"]
    mapping = requests.get(MAPPING_URL, headers=HEADERS).json()

    names = {i["id"]: i["name"] for i in mapping}
    limits = {i["id"]: i.get("limit", 0) for i in mapping}

    return prices, volumes, names, limits

@st.cache_data(ttl=1800)
def fetch_history(item_id):
    try:
        url = f"https://prices.runescape.wiki/api/v1/osrs/timeseries?id={item_id}&timestep=1h"
        data = requests.get(url, headers=HEADERS).json().get("data", [])

        prices = []
        for p in data:
            h, l = p.get("avgHighPrice"), p.get("avgLowPrice")
            if h and l:
                prices.append((h + l) / 2)
            elif h:
                prices.append(h)

        return prices if len(prices) > 5 else None
    except:
        return None
