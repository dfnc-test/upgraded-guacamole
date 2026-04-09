from utils.helpers import get_image_url
from data.fetcher import fetch_history
from config import GE_TAX, MIN_VOLUME
import pandas as pd

def calculate_flips(prices, volumes, names, limits, liquidity_mode, profit_mode):
    rows = []

    for item_id, data in prices.items():
        item_id = int(item_id)
        high, low = data.get("high"), data.get("low")
        if not high or not low:
            continue

        volume = volumes.get(str(item_id), {}).get("highPriceVolume", 0)
        if volume < MIN_VOLUME:
            continue

        real_sell = high * (1 - GE_TAX)
        margin = real_sell - low
        spread_pct = (high - low) / low

        # MODE FILTER
        if liquidity_mode:
            if volume < 50000 or spread_pct < 0.01:
                continue
        elif profit_mode:
            if spread_pct < 0.04:
                continue

        fills_per_hour = volume / 24

        # PRICING STRATEGY
        if liquidity_mode:
            buy = int(low * 1.02)
            sell = int(real_sell * 0.97)
        else:
            buy = int(low)
            sell = int(real_sell)

        qty = int(min(limits.get(item_id, 0), fills_per_hour * (0.8 if liquidity_mode else 0.4)))
        if qty < 5:
            continue

        time_to_sell = max(qty / fills_per_hour, 0.05 if liquidity_mode else 0.1)

        velocity = (margin * qty) / time_to_sell

        rows.append({
            "Item": names[item_id],
            "Buy": buy,
            "Sell": sell,
            "Margin": int(margin),
            "Volume": volume,
            "Qty": qty,
            "Velocity": int(velocity),
            "Image": get_image_url(names[item_id])
        })

    return pd.DataFrame(rows).sort_values(by="Velocity", ascending=False)
