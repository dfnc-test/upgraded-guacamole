import streamlit as st
import requests
import pandas as pd
import json
import os
from datetime import datetime

# ================= CONFIG =================
LATEST_URL      = "https://prices.runescape.wiki/api/v1/osrs/latest"
TIMESERIES_URL  = "https://prices.runescape.wiki/api/v1/osrs/timeseries"
VOLUME_URL      = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL     = "https://prices.runescape.wiki/api/v1/osrs/mapping"
ANTHROPIC_URL   = "https://api.anthropic.com/v1/messages"

HEADERS     = {"User-Agent": "GE-Trading-Dashboard"}
GE_TAX_RATE = 0.01
GE_TAX_CAP  = 5_000_000

HIGH_VALUE_THRESHOLD = 1_000_000
TOP_N_NORMAL         = 20
TOP_N_HIGH_VALUE     = 10
SAVED_TRADES_FILE    = "saved_trades.json"
# ==========================================

SMALL = "font-size:0.78rem; color: #ddd;"
LABEL = "font-size:0.7rem; color:#888; text-transform:uppercase; letter-spacing:0.04em;"


# ──────────────────────────────────────────
# Saved trades
# ──────────────────────────────────────────

def load_saved_trades() -> list:
    if os.path.exists(SAVED_TRADES_FILE):
        try:
            with open(SAVED_TRADES_FILE) as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_trades_to_file(trades: list):
    with open(SAVED_TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)

def add_saved_trade(row: dict) -> bool:
    trades = load_saved_trades()
    entry = {
        "saved_at":    datetime.now().strftime("%Y-%m-%d %H:%M"),
        "item":        row["Item"],
        "buy_at":      row["Buy"],
        "sell_at":     row["Sell"],
        "tax":         row["Tax"],
        "margin":      row["Margin"],
        "roi_pct":     row["ROI %"],
        "trade_size":  row["Trade Size"],
        "profit_flip": row["Profit/flip"],
        "image":       row["Image"],
    }
    if any(t["item"] == entry["item"] and t["buy_at"] == entry["buy_at"] for t in trades):
        return False
    trades.append(entry)
    save_trades_to_file(trades)
    return True

def remove_saved_trade(index: int):
    trades = load_saved_trades()
    if 0 <= index < len(trades):
        trades.pop(index)
        save_trades_to_file(trades)


# ──────────────────────────────────────────
# AI prompt → filter params
# ──────────────────────────────────────────

SYSTEM_PROMPT = """You are an OSRS Grand Exchange trading assistant.
The user describes what kind of trade they want in natural language.
Return ONLY JSON with filter params...
"""

def ai_parse_prompt(user_prompt: str) -> dict | None:
    try:
        resp = requests.post(
            ANTHROPIC_URL,
            headers={
                "Content-Type": "application/json",
                "x-api-key": st.secrets["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 512,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_prompt}],
            },
            timeout=15,
        )
        resp.raise_for_status()

        text = resp.json()["content"][0]["text"].strip()
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)

    except Exception as e:
        st.error(f"AI parse failed: {e}")
        return None


# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────

def ge_tax(sell_price: int) -> int:
    return min(int(sell_price * GE_TAX_RATE), GE_TAX_CAP)

def get_image_url(icon_filename: str) -> str:
    if not icon_filename:
        return ""
    return f"https://oldschool.runescape.wiki/images/{icon_filename.replace(' ', '_')}"

def stat(label: str, value: str) -> str:
    return f'<span style="{LABEL}">{label}</span><br><span style="{SMALL}">{value}</span>'


# ──────────────────────────────────────────
# Data fetching
# ──────────────────────────────────────────

@st.cache_data(ttl=60)
def fetch_data():
    prices  = requests.get(LATEST_URL, headers=HEADERS, timeout=10).json()["data"]
    volumes = requests.get(VOLUME_URL, headers=HEADERS, timeout=10).json()["data"]
    raw_map = requests.get(MAPPING_URL, headers=HEADERS, timeout=10).json()
    mapping = {item["id"]: item for item in raw_map}
    return prices, volumes, mapping


@st.cache_data(ttl=300)
def fetch_hourly_avg(item_id: int):
    try:
        r = requests.get(
            TIMESERIES_URL,
            params={"timestep": "1h", "id": item_id},
            headers=HEADERS,
            timeout=5,
        )
        data = r.json().get("data", [])[-24:]

        highs = [d["avgHighPrice"] for d in data if d.get("avgHighPrice")]
        lows  = [d["avgLowPrice"] for d in data if d.get("avgLowPrice")]

        if not highs or not lows:
            return None, None

        return sum(highs) / len(highs), sum(lows) / len(lows)

    except Exception:
        return None, None


# ──────────────────────────────────────────
# Analysis
# ──────────────────────────────────────────

DEFAULT_PARAMS = dict(
    min_volume=500,
    min_margin=50,
    min_roi=0.003,
    max_roi=0.12,
    max_fill_hrs=3.0,
    stability_thresh=0.35,
    capital=10_000_000,
    sort_by="GP/hr",
)


def analyze_items(prices, volumes, mapping, params: dict):
    capital          = int(params.get("capital", DEFAULT_PARAMS["capital"]))
    min_volume       = int(params.get("min_volume", DEFAULT_PARAMS["min_volume"]))
    min_margin       = int(params.get("min_margin", DEFAULT_PARAMS["min_margin"]))
    min_roi          = float(params.get("min_roi", DEFAULT_PARAMS["min_roi"]))
    max_roi          = float(params.get("max_roi", DEFAULT_PARAMS["max_roi"]))
    max_fill_hrs     = float(params.get("max_fill_hrs", DEFAULT_PARAMS["max_fill_hrs"]))
    stability_thresh = float(params.get("stability_thresh", DEFAULT_PARAMS["stability_thresh"]))
    sort_by          = params.get("sort_by", DEFAULT_PARAMS["sort_by"])

    rows = []

    for id_str, data in prices.items():
        item_id = int(id_str)
        meta = mapping.get(item_id, {})

        snap_high = data.get("high")
        snap_low  = data.get("low")
        if not snap_high or not snap_low:
            continue

        if snap_low == 0:
            continue

        vol_data  = volumes.get(id_str, {})
        buy_vol   = vol_data.get("highPriceVolume", 0) or 0
        sell_vol  = vol_data.get("lowPriceVolume", 0) or 0
        total_vol = buy_vol + sell_vol

        if total_vol < min_volume:
            continue

        buy_limit = meta.get("limit") or 0
        real_buy  = int(snap_low * 1.01)
        tax       = ge_tax(snap_high)
        real_sell = snap_high - tax

        real_margin = real_sell - real_buy
        if real_margin <= 0:
            continue

        roi = real_margin / real_buy
        if roi < min_roi or roi > max_roi or real_margin < min_margin:
            continue

        avg_high, avg_low = fetch_hourly_avg(item_id)

        if avg_high and avg_low and avg_low > 0:
            avg_margin = avg_high - avg_low
            if avg_margin > 0:
                stability = abs(real_margin - avg_margin) / avg_margin
                if stability > stability_thresh:
                    continue
                margin_stability = round(1 - min(stability, 1), 2)
            else:
                margin_stability = 0.5
        else:
            margin_stability = 0.5

        affordable = capital // real_buy if real_buy else 0
        market_cap = int(total_vol * 0.05)

        trade_size = min(affordable, market_cap) if buy_limit == 0 else min(affordable, buy_limit, market_cap)

        if trade_size <= 0:
            continue

        fills_per_hour = (buy_vol or total_vol / 2) / 24
        if fills_per_hour == 0:
            continue

        fill_hrs = trade_size / fills_per_hour
        if fill_hrs > max_fill_hrs:
            continue

        profit_per_flip = real_margin * trade_size
        profit_per_hour = profit_per_flip / max(fill_hrs, 0.01)

        rows.append({
            "Item": meta.get("name", "Unknown"),
            "Buy": real_buy,
            "Sell": real_sell,
            "Tax": tax,
            "Margin": real_margin,
            "ROI %": round(roi * 100, 2),
            "Volume (24h)": total_vol,
            "Buy Limit": buy_limit if buy_limit else "?",
            "Trade Size": trade_size,
            "Fill (hrs)": round(fill_hrs, 2),
            "Stability": margin_stability,
            "GP/hr": int(profit_per_hour),
            "Profit/flip": int(profit_per_flip),
            "Image": get_image_url(meta.get("icon", "")),
        })

    df = pd.DataFrame(rows)

    if df.empty:
        return df, df, 0

    if sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=(sort_by == "Fill (hrs)"))
    else:
        df = df.sort_values("GP/hr", ascending=False)

    high_value = df[df["Buy"] >= HIGH_VALUE_THRESHOLD].head(10)
    normal = df[df["Buy"] < HIGH_VALUE_THRESHOLD].head(20)

    return normal, high_value, len(df)


# ──────────────────────────────────────────
# UI helpers (FIXED)
# ──────────────────────────────────────────

def render_trade_card(row: dict, save_key: str | None = None):
    img_col, info_col = st.columns([1, 7])

    with img_col:
        if row.get("Image"):
            st.markdown(
                f'<img src="{row["Image"]}" width="36">',
                unsafe_allow_html=True,
            )
        else:
            st.markdown("⬜")

    with info_col:
        st.markdown(f"**{row['Item']}**")

        buy = f"{row['Buy']:,} gp"
        sell = f"{row['Sell']:,} gp"
        margin = f"{row['Margin']:,} gp"
        roi = f"{row['ROI %']} %"
        gphr = f"{row['GP/hr']:,}"

        vol = f"{row['Volume (24h)']:,}"
        limit = str(row["Buy Limit"])
        size = f"{row['Trade Size']:,}"
        fill = f"{row['Fill (hrs)']} h"
        stab = f"{int(row['Stability']*100)} %"

        st.markdown(f"{stat('Buy', buy)} {stat('Sell', sell)} {stat('Margin', margin)} {stat('ROI', roi)} {stat('GP/hr', gphr)}",
                    unsafe_allow_html=True)

        st.markdown(f"{stat('Volume', vol)} {stat('Limit', limit)} {stat('Size', size)} {stat('Fill', fill)} {stat('Stability', stab)}",
                    unsafe_allow_html=True)

    st.divider()


def render_section(df: pd.DataFrame, key_prefix: str):
    for i, (_, row) in enumerate(df.iterrows()):
        render_trade_card(row.to_dict(), f"{key_prefix}_{i}")


# ──────────────────────────────────────────
# STREAMLIT APP
# ──────────────────────────────────────────

st.set_page_config(page_title="OSRS GE Dashboard", layout="centered")

st.title("📊 OSRS GE Trading Dashboard")
