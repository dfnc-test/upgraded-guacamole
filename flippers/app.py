import streamlit as st
from data.fetcher import fetch_data
from logic.flips import calculate_flips
from logic.portfolio import optimize_portfolio
from ui.search import render_search
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
