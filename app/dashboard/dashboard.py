
import streamlit as st
import pandas as pd
import plotly.express as px

from app.core.database import SessionLocal
from app.core.models import MarketTick


st.set_page_config(
    page_title="Algo Trading Dashboard",
    page_icon="📈",
    layout="wide"
)

st.title("📈 Algo Trading Dashboard")
st.caption("Angel One | Live Market Data | SBIN-EQ")

# Sidebar
st.sidebar.header("Dashboard Controls")

symbol = st.sidebar.selectbox(
    "Select Stock",
    ["SBIN-EQ"]
)

if st.sidebar.button("Refresh Data"):
    st.rerun()


def load_market_data(selected_symbol):
    db = SessionLocal()

    try:
        records = (
            db.query(MarketTick)
            .filter(MarketTick.symbol == selected_symbol)
            .order_by(MarketTick.id.desc())
            .limit(1000)
            .all()
        )

        data = [
            {
                "Symbol": item.symbol,
                "Token": item.token,
                "Price": item.ltp,
                "Exchange": item.exchange,
                "Received At": item.received_at,
            }
            for item in reversed(records)
        ]

        return pd.DataFrame(data)

    finally:
        db.close()


df = load_market_data(symbol)

if df.empty:
    st.warning(
        "No market data found. Start the market-data collector "
        "during an NSE trading session."
    )
    st.stop()


# Metrics
latest_price = df["Price"].iloc[-1]
highest_price = df["Price"].max()
lowest_price = df["Price"].min()
total_ticks = len(df)

col1, col2, col3, col4 = st.columns(4)

col1.metric(
    "Latest Price",
    f"₹{latest_price:.2f}"
)

col2.metric(
    "Highest Recorded",
    f"₹{highest_price:.2f}"
)

col3.metric(
    "Lowest Recorded",
    f"₹{lowest_price:.2f}"
)

col4.metric(
    "Ticks Loaded",
    total_ticks
)


st.divider()

# Price chart
st.subheader(f"{symbol} Price Movement")

fig = px.line(
    df,
    x="Received At",
    y="Price",
    title="Recorded SBIN Price",
    markers=True
)

fig.update_layout(
    xaxis_title="Time",
    yaxis_title="Price (INR)",
    hovermode="x unified"
)

st.plotly_chart(fig, use_container_width=True)


# Recent records
st.subheader("Recent Market Data")

recent_df = df.sort_values(
    "Received At",
    ascending=False
).head(20)

st.dataframe(
    recent_df,
    use_container_width=True,
    hide_index=True
)

st.caption(
    "Data is loaded from your local SQLite database. "
    "Use Refresh Data to reload the latest records."
)

