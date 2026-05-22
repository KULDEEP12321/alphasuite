"""
Live crypto chart powered by Binance public REST + TradingView Lightweight Charts.
No API key required — Binance public endpoints are free and unauthenticated.
"""
import time
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from streamlit_lightweight_charts import renderLightweightCharts

st.set_page_config(page_title="Live Crypto Chart", layout="wide")
st.title("💹 Live Crypto Chart")
st.caption("Real-time candles from Binance · TradingView Lightweight Charts")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"]
INTERVALS = {
    "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400,
}

c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
symbol = c1.selectbox("Symbol", SYMBOLS, index=0)
interval = c2.selectbox("Interval", list(INTERVALS.keys()), index=2)
candles = c3.slider("Candles to show", 50, 1000, 300, 50)
refresh_s = c4.slider("Refresh (seconds)", 2, 60, 5)

st_autorefresh(interval=refresh_s * 1000, key="crypto_refresh")


@st.cache_data(ttl=2)
def fetch_klines(sym: str, intv: str, limit: int):
    """Pull klines from Binance public REST."""
    url = "https://api.binance.com/api/v3/klines"
    r = requests.get(url, params={"symbol": sym, "interval": intv, "limit": limit}, timeout=10)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=2)
def fetch_ticker(sym: str):
    url = "https://api.binance.com/api/v3/ticker/24hr"
    r = requests.get(url, params={"symbol": sym}, timeout=10)
    r.raise_for_status()
    return r.json()


try:
    klines = fetch_klines(symbol, interval, candles)
    ticker = fetch_ticker(symbol)
except requests.RequestException as e:
    st.error(f"Binance request failed: {e}")
    st.stop()

# Header metrics
last = float(ticker["lastPrice"])
change_pct = float(ticker["priceChangePercent"])
high = float(ticker["highPrice"])
low = float(ticker["lowPrice"])
volume = float(ticker["volume"])

m1, m2, m3, m4 = st.columns(4)
m1.metric(f"{symbol} price", f"${last:,.2f}", f"{change_pct:+.2f}% 24h")
m2.metric("24h high", f"${high:,.2f}")
m3.metric("24h low", f"${low:,.2f}")
m4.metric("24h volume", f"{volume:,.0f}")

# Transform klines into Lightweight Charts format.
# Binance kline: [openTime, open, high, low, close, volume, closeTime, ...]
candle_data = [
    {
        "time": int(k[0] // 1000),
        "open": float(k[1]),
        "high": float(k[2]),
        "low": float(k[3]),
        "close": float(k[4]),
    }
    for k in klines
]
volume_data = [
    {
        "time": int(k[0] // 1000),
        "value": float(k[5]),
        "color": "rgba(38,166,154,0.5)" if float(k[4]) >= float(k[1]) else "rgba(239,83,80,0.5)",
    }
    for k in klines
]

chart_options = {
    "height": 520,
    "layout": {
        "background": {"type": "solid", "color": "#0d1117"},
        "textColor": "#d1d4dc",
    },
    "grid": {
        "vertLines": {"color": "rgba(197,203,206,0.15)"},
        "horzLines": {"color": "rgba(197,203,206,0.15)"},
    },
    "timeScale": {"timeVisible": True, "secondsVisible": False},
    "rightPriceScale": {"borderColor": "rgba(197,203,206,0.4)"},
    "crosshair": {"mode": 1},
}

series = [
    {
        "type": "Candlestick",
        "data": candle_data,
        "options": {
            "upColor": "#26a69a",
            "downColor": "#ef5350",
            "borderVisible": False,
            "wickUpColor": "#26a69a",
            "wickDownColor": "#ef5350",
        },
    },
    {
        "type": "Histogram",
        "data": volume_data,
        "options": {
            "priceFormat": {"type": "volume"},
            "priceScaleId": "",
        },
        "priceScale": {"scaleMargins": {"top": 0.8, "bottom": 0}},
    },
]

renderLightweightCharts(
    [{"chart": chart_options, "series": series}],
    key=f"chart_{symbol}_{interval}",
)

st.caption(
    f"Last update: {time.strftime('%Y-%m-%d %H:%M:%S')} · "
    f"Data: Binance public API (no key required) · "
    f"Chart: TradingView Lightweight Charts"
)
