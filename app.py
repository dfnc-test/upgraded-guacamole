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
Your job is to translate their intent into a JSON filter config.

Return ONLY a valid JSON object — no preamble, no markdown fences — with these keys:

{
  "min_volume":        int,    // minimum 24h trade volume
  "min_margin":        int,    // minimum margin in gp
  "min_roi":           float,  // minimum ROI as a decimal (e.g. 0.005 = 0.5%)
  "max_roi":           float,  // maximum ROI (high ROI = higher risk/lower volume)
  "max_fill_hrs":      float,  // how many hours you're willing to wait for a fill
  "stability_thresh":  float,  // how much margin can deviate from 1h avg (0.0–1.0)
  "capital":           int,    // GP capital (default 10000000 if not mentioned)
  "sort_by":           string, // one of: "GP/hr", "ROI %", "Stability", "Fill (hrs)"
  "label":             string  // short human-readable description of the strategy, e.g. "Quick high-volume flips"
}

Guidelines:
- "quick money", "fast flip", "high flow": high volume (>2000), low fill time (<1h), sort by GP/hr
- "low risk", "safe", "stable": high stability_thresh (0.2), low max_roi (0.06), high min_volume
- "long term", "away", "afk", "speculative": allow high fill time (up to 24h), higher ROI ok (up to 0.20), lower volume ok
- "passive", "overnight": fill time 4–12h, moderate volume
- "high value": set capital implied by user or default, allow buy prices >1M
- If the user mentions a GP amount, use it as capital.
- Always be conservative with stability_thresh (keep it ≤ 0.5 unless user says risky).
"""

def ai_parse_prompt(user_prompt: str) -> dict | None:
    """Call Claude to translate a natural-language trade prompt into filter params."""
    try:
        resp = requests.post(
            ANTHROPIC_URL,
            headers={"Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 512,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_prompt}],
            },
            timeout=15,
        )
        text = resp.json()["content"][0]["text"].strip()
        # Strip any accidental markdown fences
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
    prices  = requests.get(LATEST_URL,  headers=HEADERS, timeout=10).json()["data"]
    volumes = requests.get(VOLUME_URL,  headers=HEADERS, timeout=10).json()["data"]
    raw_map = requests.get(MAPPING_URL, headers=HEADERS, timeout=10).json()
    mapping = {item["id"]: item for item in raw_map}
    return prices, volumes, mapping

@st.cache_data(ttl=300)
def fetch_hourly_avg(item_id: int):
    try:
        r = requests.get(
            TIMESERIES_URL,
            params={"timestep": "1h", "id": item_id},
            headers=HEADERS, timeout=5,
        )
        data = r.json().get("data", [])[-24:]
        if not data:
            return None, None
        highs = [d["avgHighPrice"] for d in data if d.get("avgHighPrice")]
        lows  = [d["avgLowPrice"]  for d in data if d.get("avgLowPrice")]
        if not highs or not lows:
            return None, None
        return sum(highs) / len(highs), sum(lows) / len(lows)
    except Exception:
        return None, None


# ──────────────────────────────────────────
# Analysis
# ──────────────────────────────────────────

DEFAULT_PARAMS = dict(
    min_volume=500, min_margin=50, min_roi=0.003,
    max_roi=0.12, max_fill_hrs=3.0, stability_thresh=0.35,
    capital=10_000_000, sort_by="GP/hr",
)

def analyze_items(prices, volumes, mapping, params: dict):
    capital           = int(params.get("capital",          DEFAULT_PARAMS["capital"]))
    min_volume        = int(params.get("min_volume",       DEFAULT_PARAMS["min_volume"]))
    min_margin        = int(params.get("min_margin",       DEFAULT_PARAMS["min_margin"]))
    min_roi           = float(params.get("min_roi",        DEFAULT_PARAMS["min_roi"]))
    max_roi           = float(params.get("max_roi",        DEFAULT_PARAMS["max_roi"]))
    max_fill_hrs      = float(params.get("max_fill_hrs",   DEFAULT_PARAMS["max_fill_hrs"]))
    stability_thresh  = float(params.get("stability_thresh", DEFAULT_PARAMS["stability_thresh"]))
    sort_by           = params.get("sort_by", DEFAULT_PARAMS["sort_by"])

    rows = []

    for id_str, data in prices.items():
        item_id   = int(id_str)
        meta      = mapping.get(item_id, {})
        snap_high = data.get("high")
        snap_low  = data.get("low")
        if not snap_high or not snap_low or snap_low == 0:
            continue

        vol_data  = volumes.get(id_str, {})
        buy_vol   = vol_data.get("highPriceVolume", 0) or 0
        sell_vol  = vol_data.get("lowPriceVolume",  0) or 0
        total_vol = buy_vol + sell_vol
        if total_vol < min_volume:
            continue

        buy_limit   = meta.get("limit") or 0
        real_buy    = int(snap_low * 1.01)
        tax         = ge_tax(snap_high)
        real_sell   = snap_high - tax
        real_margin = real_sell - real_buy
        if real_margin <= 0:
            continue

        roi = real_margin / real_buy
        if roi < min_roi or real_margin < min_margin or roi > max_roi:
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

        affordable = capital // real_buy if real_buy > 0 else 0
        market_cap = int(total_vol * 0.05)
        trade_size = (
            min(affordable, buy_limit, market_cap) if buy_limit > 0
            else min(affordable, market_cap)
        )
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
        name = meta.get("name", "Unknown")
        icon = meta.get("icon", "")

        rows.append({
            "Item":         name,
            "Buy":          real_buy,
            "Sell":         real_sell,
            "Tax":          tax,
            "Margin":       real_margin,
            "ROI %":        round(roi * 100, 2),
            "Volume (24h)": total_vol,
            "Buy Limit":    buy_limit if buy_limit else "?",
            "Trade Size":   trade_size,
            "Fill (hrs)":   round(fill_hrs, 2),
            "Stability":    margin_stability,
            "GP/hr":        int(profit_per_hour),
            "Profit/flip":  int(profit_per_flip),
            "Image":        get_image_url(icon),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df, df, 0

    # Sort by AI-chosen metric, fallback to GP/hr
    if sort_by in df.columns:
        asc = sort_by == "Fill (hrs)"
        df = df.sort_values(sort_by, ascending=asc)
    else:
        df = df.sort_values("GP/hr", ascending=False)

    high_value = df[df["Buy"] >= HIGH_VALUE_THRESHOLD].head(TOP_N_HIGH_VALUE)
    normal     = df[df["Buy"] <  HIGH_VALUE_THRESHOLD].head(TOP_N_NORMAL)
    return normal, high_value, len(df)


# ──────────────────────────────────────────
# UI helpers
# ──────────────────────────────────────────

def render_trade_card(row: dict, save_key: str | None = None):
    img_col, info_col = st.columns([1, 7])
    with img_col:
        if row.get("Image"):
            st.markdown(
                f'<img src="{row["Image"]}" width="36" '
                f'style="margin-top:4px; image-rendering:pixelated;">',
                unsafe_allow_html=True,
            )
        else:
            st.markdown("⬜", unsafe_allow_html=True)

    with info_col:
        title_col, btn_col = st.columns([6, 1])
        with title_col:
            st.markdown(
                f'<span style="font-size:0.88rem;font-weight:600;">{row["Item"]}</span>',
                unsafe_allow_html=True,
            )
        if save_key:
            with btn_col:
                if st.button("💾", key=save_key, help="Save this trade"):
                    if add_saved_trade(row):
                        st.toast(f"✅ {row['Item']} saved!")
                    else:
                        st.toast("Already saved.", icon="ℹ️")

        st.markdown(
            f"{stat('Buy', f\"{row['Buy']:,} gp\")} &nbsp;&nbsp; "
            f"{stat('Sell', f\"{row['Sell']:,} gp\")} &nbsp;&nbsp; "
            f"{stat('Margin', f\"{row['Margin']:,} gp\")} &nbsp;&nbsp; "
            f"{stat('ROI', f\"{row['ROI %']} %\")} &nbsp;&nbsp; "
            f"{stat('GP/hr', f\"{row['GP/hr']:,}\")}",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"{stat('Volume', f\"{row['Volume (24h)']:,}\")} &nbsp;&nbsp; "
            f"{stat('Limit', str(row['Buy Limit']))} &nbsp;&nbsp; "
            f"{stat('Size', f\"{row['Trade Size']:,}\")} &nbsp;&nbsp; "
            f"{stat('Fill', f\"{row['Fill (hrs)']} h\")} &nbsp;&nbsp; "
            f"{stat('Stability', f\"{int(row['Stability']*100)} %\")}",
            unsafe_allow_html=True,
        )
    st.divider()


def render_section(df: pd.DataFrame, key_prefix: str):
    if df.empty:
        st.info("No trades matched. Try a different prompt or lower your capital requirement.")
        return
    for i, (_, row) in enumerate(df.iterrows()):
        render_trade_card(row.to_dict(), save_key=f"{key_prefix}_{i}")


# ──────────────────────────────────────────
# Page
# ──────────────────────────────────────────

st.set_page_config(page_title="OSRS GE Dashboard", layout="centered")

st.markdown("<h3 style='margin-bottom:4px'>📊 OSRS GE Trading Dashboard</h3>", unsafe_allow_html=True)

# ── AI prompt bar ──────────────────────────────────────────────────────────────
st.markdown(
    '<p style="font-size:0.8rem;color:#888;margin-bottom:4px">'
    'Describe the trade you want in plain English:</p>',
    unsafe_allow_html=True,
)

EXAMPLES = [
    "Quick high-volume flips, minimal risk, I have 5m gp",
    "I'll be AFK for a few hours, looking for a passive trade",
    "Long-term speculative with high ROI, 50m capital",
    "Safe overnight trade, nothing too risky",
]

prompt_col, btn_col, refresh_col = st.columns([6, 1, 1])
with prompt_col:
    user_prompt = st.text_input(
        "prompt",
        value=st.session_state.get("last_prompt", ""),
        placeholder=EXAMPLES[0],
        label_visibility="collapsed",
    )
with btn_col:
    search_clicked = st.button("🔍 Go", use_container_width=True)
with refresh_col:
    refresh_clicked = st.button("🔄", use_container_width=True, help="Refresh prices")

# Quick-example chips
st.markdown('<p style="font-size:0.72rem;color:#666;margin:2px 0 6px">Quick examples:</p>', unsafe_allow_html=True)
chip_cols = st.columns(len(EXAMPLES))
for col, ex in zip(chip_cols, EXAMPLES):
    if col.button(ex[:28] + "…", key=f"chip_{ex[:10]}", use_container_width=True):
        st.session_state["last_prompt"] = ex
        st.session_state["run_prompt"]  = ex
        st.rerun()

# ── Handle refresh ─────────────────────────────────────────────────────────────
if refresh_clicked:
    fetch_data.clear()
    fetch_hourly_avg.clear()
    st.toast("♻️ Prices refreshed!")
    st.rerun()

# ── Resolve active params ──────────────────────────────────────────────────────
active_prompt = st.session_state.pop("run_prompt", None) or (user_prompt if search_clicked else None)

if active_prompt:
    st.session_state["last_prompt"] = active_prompt
    with st.spinner("🤖 Interpreting your request…"):
        parsed = ai_parse_prompt(active_prompt)
    if parsed:
        st.session_state["active_params"] = parsed
        st.session_state["active_label"]  = parsed.get("label", active_prompt)

active_params = st.session_state.get("active_params", DEFAULT_PARAMS)
active_label  = st.session_state.get("active_label",  "Default (balanced)")

st.markdown(
    f'<p style="font-size:0.75rem;color:#aaa;margin-bottom:8px">'
    f'Strategy: <b>{active_label}</b> &nbsp;·&nbsp; '
    f'Capital: <b>{active_params.get("capital", DEFAULT_PARAMS["capital"]):,} gp</b> &nbsp;·&nbsp; '
    f'Sort: <b>{active_params.get("sort_by", "GP/hr")}</b>'
    f'</p>',
    unsafe_allow_html=True,
)

# ── Fetch & analyse ────────────────────────────────────────────────────────────
with st.spinner("Fetching & analysing…"):
    prices, volumes, mapping_data = fetch_data()
    normal, high_value, total_found = analyze_items(prices, volumes, mapping_data, active_params)

st.caption(f"🔍 {total_found} viable trades found")

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_normal, tab_high, tab_saved = st.tabs(["🟢 Flips", "🔵 High Value", "📌 Saved Trades"])

with tab_normal:
    render_section(normal, key_prefix="n")

with tab_high:
    render_section(high_value, key_prefix="h")

with tab_saved:
    saved = load_saved_trades()
    if not saved:
        st.info("No saved trades yet. Hit 💾 on any trade to save it for reference.")
    else:
        st.caption(
            "Prices locked at save time — use these to decide your sell price "
            "even after the live market has moved."
        )
        for i, t in enumerate(saved):
            img_col, info_col, del_col = st.columns([1, 7, 1])
            with img_col:
                if t.get("image"):
                    st.markdown(
                        f'<img src="{t["image"]}" width="36" '
                        f'style="margin-top:4px;image-rendering:pixelated;">',
                        unsafe_allow_html=True,
                    )
            with info_col:
                st.markdown(
                    f'<span style="font-size:0.88rem;font-weight:600;">{t["item"]}</span>'
                    f'<span style="{LABEL};margin-left:8px;">saved {t["saved_at"]}</span>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"{stat('Bought at',    f\"{t['buy_at']:,} gp\")} &nbsp;&nbsp; "
                    f"{stat('Target sell',  f\"{t['sell_at']:,} gp\")} &nbsp;&nbsp; "
                    f"{stat('Tax',          f\"{t['tax']:,} gp\")} &nbsp;&nbsp; "
                    f"{stat('Margin',       f\"{t['margin']:,} gp\")} &nbsp;&nbsp; "
                    f"{stat('ROI',          f\"{t['roi_pct']} %\")}",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"{stat('Size',         f\"{t['trade_size']:,}\")} &nbsp;&nbsp; "
                    f"{stat('Total profit', f\"{t['profit_flip']:,} gp\")}",
                    unsafe_allow_html=True,
                )
            with del_col:
                if st.button("🗑️", key=f"del_{i}", help="Remove"):
                    remove_saved_trade(i)
                    st.rerun()
            st.divider()

        if st.button("🗑️ Clear all saved trades"):
            save_trades_to_file([])
            st.rerun()

st.markdown(
    '<sub style="color:#555">Prices from prices.runescape.wiki · '
    'Stability = live margin vs 1h avg · GP/hr assumes continuous flipping</sub>',
    unsafe_allow_html=True,
)
