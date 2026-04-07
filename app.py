# ---------- CALCULATIONS ----------
def calculate_flips(prices, volumes, names, limits, min_vol=MIN_VOLUME):
    rows = []
    for item_id_str, data in prices.items():
        item_id = int(item_id_str)
        high, low = data.get("high"), data.get("low")
        if not high or not low or low <= 0:
            continue

        vol_data = volumes.get(str(item_id), {})
        volume = vol_data.get("highPriceVolume",0) + vol_data.get("lowPriceVolume",0)
        if volume < min_vol:
            continue

        real_sell = high * (1 - GE_TAX)
        margin = real_sell - low
        if margin < MIN_MARGIN:
            continue

        roi = margin / low
        buy_limit = limits.get(item_id, 0)
        profit_limit = margin * buy_limit
        fills_per_hour = volume / 24
        time_to_sell = min(buy_limit / fills_per_hour, BUY_LIMIT_HOURS) if fills_per_hour>0 else 0.1
        profit_hour = profit_limit / max(time_to_sell, 0.1)

        mid_price = (high + low)/2
        sma = mid_price
        ema = (mid_price*0.7 + low*0.3)
        momentum = ((high-low)/low)*100 if low>0 else 0
        vol_spike = min(volume/10000,5)

        # ----- Z-SCORE using historical mid-prices -----
        hist = fetch_history(item_id)
        if hist is not None and len(hist) >= 3:
            hist_mean = hist.mean()
            hist_std = hist.std(ddof=0)
            z = (mid_price - hist_mean) / hist_std if hist_std > 0 else 0.0
        else:
            z = "N/A"  # fallback if no history

        # ----- Signal based on Z-score -----
        if z != "N/A":
            if z < -0.5 and vol_spike > 1:
                signal = "BUY"
            elif z > 0.5:
                signal = "SELL"
            else:
                signal = "HOLD"
        else:
            signal = "HOLD"

        # Confidence
        volume_score = min(volume / 100_000, 1)
        margin_score = min(margin / 1000, 1)
        roi_score = min(roi / 0.1, 1)
        confidence = round((volume_score + margin_score + roi_score)/3*100,1)

        rows.append({
            "Image": get_image_url(names.get(item_id,"Unknown")),
            "Item": names.get(item_id,"Unknown"),
            "Buy": low,
            "Sell": int(real_sell),
            "Margin": int(margin),
            "ROI %": round(roi*100,2),
            "Volume": volume,
            "Profit/Hr": int(profit_hour),
            "Conf": confidence,
            "SMA": int(sma),
            "EMA": int(ema),
            "Momentum": round(momentum,2),
            "Z": round(z,2) if z != "N/A" else "N/A",
            "Vol Spike": round(vol_spike,2),
            "Signal": signal
        })

    return pd.DataFrame(rows).sort_values(by="Profit/Hr", ascending=False).head(20)
