"""Midweek Merchant dashboard. Run with:  uv run streamlit run app/streamlit_app.py"""

import streamlit as st

st.set_page_config(page_title="Midweek Merchant", page_icon=":material/sports_soccer:", layout="wide")

pages = [
    st.Page("views/home.py", title="Home", icon=":material/home:", default=True),
    st.Page("views/my_team.py", title="My team", icon=":material/groups:"),
    st.Page("views/projections.py", title="Projections", icon=":material/insights:"),
    st.Page("views/best_squad.py", title="Best squad", icon=":material/star:"),
    st.Page("views/chips.py", title="Chips", icon=":material/bolt:"),
    st.Page("views/league.py", title="Mini-league", icon=":material/emoji_events:"),
    st.Page("views/hindcast.py", title="Hindcast", icon=":material/history:"),
    st.Page("views/model_health.py", title="Model health", icon=":material/monitor_heart:"),
]
st.navigation(pages).run()
