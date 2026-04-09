import streamlit as st
from data.fetcher import fetch_data
from logic.flips import calculate_flips
from logic.portfolio import optimize_portfolio
from ui.search import render_search
from logic.tracking import analyze_slots
from logic.inventory import load_inventory, add_item, evaluate_inventory
from ui.watchlist import render_watchlist

st.set_page_config(layout="wide")
st.title("📊 OSRS GE Dashboard")

gp = st.number_input("💰 GP", value=10_000_000)

liquidity_mode = st.toggle("⚡ Liquidity Mode")
profit_mode = st.toggle("🔥 Profit Mode")

prices, volumes, names, limits = fetch_data()

render_search(prices, volumes, names)

df = calculate_flips(prices, volumes, names, limits, liquidity_mode, profit_mode)

st.subheader("📈 Opportunities")
st.dataframe(df.head(20))

st.subheader("🧠 Portfolio")
st.dataframe(optimize_portfolio(df, gp))

render_watchlist()

st.subheader("🎒 Inventory Trader")

inventory = load_inventory()

item_name = st.text_input("Item Name (for inventory)")
buy_price = st.number_input("Buy Price", value=0)
target_sell = st.number_input("Target Sell Price", value=0)

if st.button("➕ Add to Inventory"):
    item_id = next((k for k, v in names.items() if v.lower() == item_name.lower()), None)

    if item_id:
        add_item(inventory, {
            "id": item_id,
            "name": item_name,
            "buy_price": buy_price,
            "target_sell": target_sell
        })
        st.success("Added!")
    else:
        st.error("Item not found")

inv_results = evaluate_inventory(inventory, prices, volumes)

st.dataframe(inv_results)

st.subheader("📊 Slot Efficiency")

slot_data = analyze_slots(df.head(20))
st.dataframe(slot_data)
