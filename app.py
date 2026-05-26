import streamlit as st
import requests
import pandas as pd

# ================= CONFIG =================
LATEST_URL      = "https://prices.runescape.wiki/api/v1/osrs/latest"
TIMESERIES_URL  = "https://prices.runescape.wiki/api/v1/osrs/timeseries"   # ?timestep=1h&id=...
VOLUME_URL      = "https://prices.runescape.wiki/api/v1/osrs/24h"
MAPPING_URL     = "https://prices.runescape.wiki/api/v1/osrs/mapping"

HEADERS = {"User-Agent": "GE-Trading-Dashboard"}

GE_TAX_RATE  = 0.01          # 1 % on the sell side
GE_TAX_CAP   = 5_000_000     # tax never exceeds 5 M gp

HIGH_VALUE_THRESHOLD = 1_000_000   # gp — split into two tables
TOP_N_NORMAL     = 20
TOP_N_HIGH_VALUE = 10
# ==========================================


# ---------- Pure helpers ----------

def ge_tax(sell_price: int) -> int:
    """Return the GE tax paid when selling at sell_price."""
    return min(int(sell_price * GE_TAX_RATE), GE_TAX_CAP)


def get_image_url(name: str) -> str:
    formatted = (
        name.replace(" ", "_")
            .replace("'", "%27")
            .replace("(", "")
            .replace(")", "")
    )
    return f"https://oldschool.runescape.wiki/images/{formatted}.png"


# ---------- Data fetching ----------

@st.cache_data(ttl=60)
def fetch_data():
    """
    Returns
    -------
    prices  : dict  id_str -> {high, low, highTime, lowTime}
    volumes : dict  id_str -> {highPriceVolume, lowPriceVolume, ...}
    mapping : dict  id_int -> {name, limit, members, value, ...}
    """
    prices  = requests.get(LATEST_URL,  headers=HEADERS, timeout=10).json()["data"]
    volumes = requests.get(VOLUME_URL,  headers=HEADERS, timeout=10).json()["data"]
    raw_map = requests.get(MAPPING_URL, headers=HEADERS, timeout=10).json()

    # Keyed by int id for easy lookup
    mapping = {item["id"]: item for item in raw_map}
    return prices, volumes, mapping


@st.cache_data(ttl=300)
def fetch_hourly_avg(item_id: int):
    """
    Fetch the last 24 data-points at 1 h resolution and return
    (avg_high, avg_low) over that window.  Returns (None, None) on failure.
    """
    try:
        r = requests.get(
            TIMESERIES_URL,
            params={"timestep": "1h", "id": item_id},
            headers=HEADERS,
            timeout=5,
        )
        data = r.json().get("data", [])[-24:]   # last 24 hours
        if not data:
            return None, None
        highs = [d["avgHighPrice"] for d in data if d.get("avgHighPrice")]
        lows  = [d["avgLowPrice"]  for d in data if d.get("avgLowPrice")]
        if not highs or not lows:
            return None, None
        return sum(highs) / len(highs), sum(lows) / len(lows)
    except Exception:
        return None, None


# ---------- Analysis ----------

MODE_PARAMS = {
    "Safe": dict(
        min_volume       = 1_000,
        min_margin       = 100,
        min_roi          = 0.005,
        max_roi          = 0.10,
        max_fill_hrs     = 2.0,
        stability_thresh = 0.30,   # snapshot margin must be within 30 % of 1h avg
    ),
    "Relaxed": dict(
        min_volume       = 200,
        min_margin       = 30,
        min_roi          = 0.002,
        max_roi          = 0.20,
        max_fill_hrs     = 6.0,
        stability_thresh = 0.60,
    ),
}


def analyze_items(prices, volumes, mapping, capital: int, mode: str):
    p = MODE_PARAMS[mode]

    rows = []

    for id_str, data in prices.items():
        item_id = int(id_str)
        meta    = mapping.get(item_id, {})

        snap_high = data.get("high")
        snap_low  = data.get("low")
        if not snap_high or not snap_low or snap_low == 0:
            continue

        # ── 1. Volume from the 24 h endpoint ──────────────────────────────
        vol_data   = volumes.get(id_str, {})
        buy_vol    = vol_data.get("highPriceVolume", 0) or 0   # items bought at high
        sell_vol   = vol_data.get("lowPriceVolume",  0) or 0   # items sold  at low
        total_vol  = buy_vol + sell_vol

        if total_vol < p["min_volume"]:
            continue

        # ── 2. Buy limit ───────────────────────────────────────────────────
        buy_limit = meta.get("limit") or 0    # 0 means unknown; don't filter out

        # ── 3. Realistic execution prices ─────────────────────────────────
        # Buy slightly above low, sell slightly below high (typical slip)
        real_buy  = int(snap_low  * 1.01)
        tax       = ge_tax(snap_high)
        real_sell = snap_high - tax            # what you actually receive

        real_margin = real_sell - real_buy
        if real_margin <= 0:
            continue

        roi = real_margin / real_buy
        if roi < p["min_roi"] or real_margin < p["min_margin"]:
            continue
        if roi > p["max_roi"]:
            continue

        # ── 4. Margin stability vs 1 h average ────────────────────────────
        avg_high, avg_low = fetch_hourly_avg(item_id)
        if avg_high and avg_low and avg_low > 0:
            avg_margin = avg_high - avg_low
            if avg_margin > 0:
                stability = abs(real_margin - avg_margin) / avg_margin
                if stability > p["stability_thresh"]:
                    continue          # snapshot is an outlier spike — skip
            margin_stability = round(1 - min(stability, 1), 2) if avg_margin > 0 else 0.5
        else:
            margin_stability = 0.5   # unknown; neutral score

        # ── 5. Trade-size & fill-time ──────────────────────────────────────
        affordable  = capital // real_buy if real_buy > 0 else 0
        market_cap  = int(total_vol * 0.05)   # don't move more than 5 % of daily vol

        if buy_limit > 0:
            trade_size = min(affordable, buy_limit, market_cap)
        else:
            trade_size = min(affordable, market_cap)

        if trade_size <= 0:
            continue

        # Fill-time: how many hours to buy trade_size given ~half the volume buys
        fills_per_hour = (buy_vol or total_vol / 2) / 24
        if fills_per_hour == 0:
            continue

        fill_hrs = trade_size / fills_per_hour
        if fill_hrs > p["max_fill_hrs"]:
            continue

        # ── 6. Profit-per-hour (the primary ranking metric) ───────────────
        profit_per_flip = real_margin * trade_size
        profit_per_hour = profit_per_flip / max(fill_hrs, 0.01)

        name = meta.get("name", "Unknown")

        rows.append({
            "Item":           name,
            "Buy":            real_buy,
            "Sell":           real_sell,
            "Tax":            tax,
            "Margin":         real_margin,
            "ROI %":          round(roi * 100, 2),
            "Volume (24h)":   total_vol,
            "Buy Limit":      buy_limit if buy_limit else "?",
            "Trade Size":     trade_size,
            "Fill (hrs)":     round(fill_hrs, 2),
            "Stability":      margin_stability,
            "GP/hr":          int(profit_per_hour),
            "Profit/flip":    int(profit_per_flip),
            "Image":          get_image_url(name),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df, df, 0

    df = df.sort_values("GP/hr", ascending=False)

    high_value = df[df["Buy"] >= HIGH_VALUE_THRESHOLD].head(TOP_N_HIGH_VALUE)
    normal     = df[df["Buy"] <  HIGH_VALUE_THRESHOLD].head(TOP_N_NORMAL)

    return normal, high_value, len(df)


# ---------- UI ----------

st.set_page_config(page_title="OSRS GE Dashboard", layout="centered")
st.title("📊 OSRS GE Trading Dashboard")

col1, col2 = st.columns(2)
with col1:
    mode = st.selectbox("Mode", ["Safe", "Relaxed"])
with col2:
    capital = st.number_input("Available GP", value=10_000_000, step=1_000_000, min_value=10_000)

with st.spinner("Fetching prices…"):
    prices, volumes, mapping = fetch_data()

with st.spinner("Analysing trades…"):
    normal, high_value, total_found = analyze_items(prices, volumes, mapping, int(capital), mode)

st.caption(f"🔍 {total_found} viable trades found • sorted by GP/hr")

# ── helper to render a table section ──────────────────────────────────────────
def render_section(df: pd.DataFrame):
    if df.empty:
        st.info("No trades found for this category. Try Relaxed mode or higher capital.")
        return

    for _, row in df.iterrows():
        with st.container():
            cols = st.columns([1, 5])

            with cols[0]:
                try:
                    st.image(row["Image"], width=48)
                except Exception:
                    st.write("—")

            with cols[1]:
                st.markdown(f"**{row['Item']}**")

                c1, c2, c3 = st.columns(3)
                c1.metric("Buy",  f"{row['Buy']:,} gp")
                c2.metric("Sell", f"{row['Sell']:,} gp")
                c3.metric("Margin", f"{row['Margin']:,} gp")

                c4, c5, c6 = st.columns(3)
                c4.metric("ROI",     f"{row['ROI %']} %")
                c5.metric("GP / hr", f"{row['GP/hr']:,}")
                c6.metric("Profit / flip", f"{row['Profit/flip']:,}")

                c7, c8, c9 = st.columns(3)
                c7.metric("Volume (24h)", f"{row['Volume (24h)']:,}")
                c8.metric("Buy limit",    str(row["Buy Limit"]))
                c9.metric("Fill time",    f"{row['Fill (hrs)']} h")

                c10, c11, _ = st.columns(3)
                c10.metric("Trade size",     f"{row['Trade Size']:,}")
                c11.metric("Stability",      f"{int(row['Stability']*100)} %")

            st.divider()


st.subheader("🟢 High-Liquidity Flips")
render_section(normal)

st.subheader("🔵 High-Value Trades  (≥ 1 M gp)")
render_section(high_value)

st.markdown(
    "<sub>Prices from [prices.runescape.wiki](https://prices.runescape.wiki). "
    "Margin stability compares the live snapshot against the 1 h average. "
    "GP/hr assumes continuous flipping of the calculated trade size.</sub>",
    unsafe_allow_html=True,
)
