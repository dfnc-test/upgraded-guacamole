import streamlit as st
from logic.analyzer import analyze_item

def render_search(prices, volumes, names):
    st.subheader("🔎 Item Analyzer")

    query = st.text_input("Search item")

    if query:
        res = analyze_item(query, prices, volumes, names)
        if res:
            st.write(res)
        else:
            st.warning("Not found")
