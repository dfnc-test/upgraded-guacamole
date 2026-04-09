from data.fetcher import fetch_history
from config import GE_TAX

def analyze_item(item_name, prices, volumes, names):
    item_id = next((k for k, v in names.items() if v.lower() == item_name.lower()), None)
    if not item_id:
        return None

    data = prices.get(str(item_id))
    if not data:
        return None

    high, low = data["high"], data["low"]
    volume = volumes.get(str(item_id), {}).get("highPriceVolume", 0)

    hist = fetch_history(item_id)
    if not hist:
        return None

    momentum = (hist[-1] - hist[-4]) / hist[-4]
    real_sell = high * (1 - GE_TAX)
    margin = real_sell - low

    return {
        "entry": int(low * 1.01),
        "exit": int(real_sell * 0.99),
        "margin": int(margin),
        "momentum": round(momentum, 3),
        "volume": volume
    }
