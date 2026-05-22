"""
Live market chart for crypto (Binance, real-time) and US stocks (yfinance, ~15min delayed).
TradingView Lightweight Charts for rendering. No API keys required.
"""
import time
import requests
import pandas as pd
import streamlit as st
import yfinance as yf
from streamlit_autorefresh import st_autorefresh
from streamlit_lightweight_charts import renderLightweightCharts

st.set_page_config(page_title="Live Market Chart", layout="wide")

st.markdown(
    """
    <style>
        .block-container { padding-top: 1.5rem; }
        .market-hero {
            background: linear-gradient(120deg, #1e3a8a 0%, #6366f1 60%, #8b5cf6 100%);
            padding: 1.1rem 1.6rem;
            border-radius: 14px;
            margin-bottom: 1.25rem;
            color: white;
            box-shadow: 0 6px 24px rgba(99,102,241,0.18);
        }
        .market-hero h1 { margin: 0; font-size: 1.7rem; font-weight: 700; }
        .market-hero p { margin: 0.2rem 0 0 0; opacity: 0.85; font-size: 0.9rem; }
        .section-h {
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: #888;
            margin: 1rem 0 0.4rem 0;
            font-weight: 600;
        }
        [data-testid="stMetric"] {
            background: rgba(255,255,255,0.025);
            border: 1px solid rgba(255,255,255,0.07);
            padding: 0.6rem 0.85rem;
            border-radius: 10px;
            transition: border-color 0.15s ease, background 0.15s ease;
            overflow: hidden;
        }
        [data-testid="stMetric"]:hover {
            border-color: rgba(99,102,241,0.5);
            background: rgba(99,102,241,0.05);
        }
        [data-testid="stMetricValue"] {
            font-size: 1.15rem !important;
            font-weight: 600;
        }
        [data-testid="stMetricLabel"] { font-size: 0.7rem !important; }
        [data-testid="stMetricDelta"] { font-size: 0.78rem !important; }
        .price-panel {
            padding: 1rem 1.2rem;
            background: rgba(255,255,255,0.025);
            border-radius: 12px;
            border: 1px solid rgba(255,255,255,0.07);
            height: 100%;
        }
        .price-panel .sym { font-size: 0.72rem; color: #888; letter-spacing: 0.08em; text-transform: uppercase; }
        .price-panel .px { font-size: 2.1rem; font-weight: 700; color: #fafafa; margin-top: 0.25rem; line-height: 1; }
        .price-panel .delta { font-size: 1rem; margin-top: 0.4rem; font-weight: 500; }
        .price-panel .ohlc { margin-top: 0.9rem; font-size: 0.82rem; color: #aaa; line-height: 1.6; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="market-hero">
        <h1>💹 Live Market Chart</h1>
        <p>Crypto from Binance (real-time) · Stocks from Yahoo Finance (~15 min delayed) · No API keys</p>
    </div>
    """,
    unsafe_allow_html=True,
)


CRYPTO_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
STOCK_SYMBOLS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META", "SPY", "QQQ"]
CRYPTO_INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"]
STOCK_INTERVALS = ["1m", "5m", "15m", "30m", "1h", "1d"]
YF_PERIOD = {"1m": "5d", "5m": "1mo", "15m": "1mo", "30m": "1mo", "1h": "3mo", "1d": "2y"}


def _reset_symbol():
    new_class = st.session_state["asset_class"]
    st.session_state["symbol"] = CRYPTO_SYMBOLS[0] if new_class == "Crypto" else STOCK_SYMBOLS[0]
    valid = CRYPTO_INTERVALS if new_class == "Crypto" else STOCK_INTERVALS
    if st.session_state.get("interval") not in valid:
        st.session_state["interval"] = "15m" if "15m" in valid else valid[0]


if "asset_class" not in st.session_state:
    st.session_state["asset_class"] = "Crypto"
if "symbol" not in st.session_state:
    st.session_state["symbol"] = "BTCUSDT"
if "interval" not in st.session_state:
    st.session_state["interval"] = "15m"


asset_class = st.segmented_control(
    "Market",
    ["Crypto", "Stocks"],
    key="asset_class",
    on_change=_reset_symbol,
)
asset_class = asset_class or "Crypto"

symbols = CRYPTO_SYMBOLS if asset_class == "Crypto" else STOCK_SYMBOLS
intervals = CRYPTO_INTERVALS if asset_class == "Crypto" else STOCK_INTERVALS


# --- Data fetchers ---
@st.cache_data(ttl=5, show_spinner=False)
def fetch_binance_klines(sym, intv, limit=300):
    r = requests.get(
        "https://api.binance.com/api/v3/klines",
        params={"symbol": sym, "interval": intv, "limit": limit},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=5, show_spinner=False)
def fetch_binance_ticker(sym):
    r = requests.get(
        "https://api.binance.com/api/v3/ticker/24hr",
        params={"symbol": sym},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=15, show_spinner=False)
def fetch_yf_klines(sym, intv, period):
    return yf.Ticker(sym).history(period=period, interval=intv, auto_adjust=False)


@st.cache_data(ttl=15, show_spinner=False)
def fetch_yf_quote(sym):
    info = yf.Ticker(sym).fast_info
    return {
        "last": info.get("lastPrice") or 0,
        "prev": info.get("previousClose") or 0,
        "high": info.get("dayHigh") or 0,
        "low": info.get("dayLow") or 0,
        "vol": info.get("tenDayAverageVolume") or 0,
    }


def get_quote(sym, klass):
    if klass == "Crypto":
        t = fetch_binance_ticker(sym)
        return {
            "last": float(t["lastPrice"]),
            "pct": float(t["priceChangePercent"]),
            "high": float(t["highPrice"]),
            "low": float(t["lowPrice"]),
            "vol": float(t["volume"]),
        }
    q = fetch_yf_quote(sym)
    pct = ((q["last"] - q["prev"]) / q["prev"] * 100) if q["prev"] else 0
    return {"last": q["last"], "pct": pct, "high": q["high"], "low": q["low"], "vol": q["vol"]}


# --- Watchlist row ---
st.markdown('<div class="section-h">Watchlist · click a symbol to switch</div>', unsafe_allow_html=True)
cols = st.columns(len(symbols))
for i, sym in enumerate(symbols):
    with cols[i]:
        try:
            q = get_quote(sym, asset_class)
            marker = "● " if sym == st.session_state["symbol"] else ""
            st.metric(f"{marker}{sym}", f"${q['last']:,.2f}", f"{q['pct']:+.2f}%")
            if st.button("Select", key=f"sel_{sym}", use_container_width=True):
                st.session_state["symbol"] = sym
                st.rerun()
        except Exception:
            st.error(f"{sym} N/A")


# --- Controls ---
st.markdown('<div class="section-h">View</div>', unsafe_allow_html=True)
c1, c2, c3 = st.columns([3, 4, 2])

with c1:
    interval = st.segmented_control(
        "Interval", intervals, key="interval",
    ) or st.session_state["interval"]

with c2:
    indicators = st.pills(
        "Indicators",
        ["SMA 20", "SMA 50", "EMA 9", "Volume"],
        selection_mode="multi",
        default=["SMA 20", "Volume"],
    ) or []

with c3:
    refresh_s = st.slider("Refresh (s)", 2, 60, 10)

st_autorefresh(interval=refresh_s * 1000, key="mkt_refresh")


# --- Fetch chart data ---
sym = st.session_state["symbol"]
try:
    if asset_class == "Crypto":
        raw = fetch_binance_klines(sym, interval, 300)
        df = pd.DataFrame(
            raw,
            columns=["t", "o", "h", "l", "c", "v", "ct", "qv", "n", "tbb", "tbq", "i"],
        )
        df["t"] = df["t"] // 1000
        df[["o", "h", "l", "c", "v"]] = df[["o", "h", "l", "c", "v"]].astype(float)
    else:
        period = YF_PERIOD.get(interval, "1mo")
        ydf = fetch_yf_klines(sym, interval, period)
        if ydf.empty:
            st.warning(f"No data returned for {sym} at {interval}. Try a different interval.")
            st.stop()
        df = pd.DataFrame(
            {
                "t": (ydf.index.astype("int64") // 10**9).astype(int),
                "o": ydf["Open"].astype(float),
                "h": ydf["High"].astype(float),
                "l": ydf["Low"].astype(float),
                "c": ydf["Close"].astype(float),
                "v": ydf["Volume"].astype(float),
            }
        ).reset_index(drop=True)
except Exception as e:
    st.error(f"Failed to fetch data: {e}")
    st.stop()


# --- Build series ---
candles = [
    {"time": int(r.t), "open": r.o, "high": r.h, "low": r.l, "close": r.c}
    for r in df.itertuples()
]
volume = [
    {
        "time": int(r.t),
        "value": r.v,
        "color": "rgba(38,166,154,0.5)" if r.c >= r.o else "rgba(239,83,80,0.5)",
    }
    for r in df.itertuples()
]

series = [
    {
        "type": "Candlestick",
        "data": candles,
        "options": {
            "upColor": "#26a69a",
            "downColor": "#ef5350",
            "borderVisible": False,
            "wickUpColor": "#26a69a",
            "wickDownColor": "#ef5350",
        },
    },
]


def _line_from(values, color, title):
    line = [
        {"time": int(t), "value": float(v)}
        for t, v in zip(df["t"], values)
        if pd.notna(v)
    ]
    return {
        "type": "Line",
        "data": line,
        "options": {"color": color, "lineWidth": 2, "title": title, "priceLineVisible": False, "lastValueVisible": False},
    }


if "SMA 20" in indicators:
    series.append(_line_from(df["c"].rolling(20).mean(), "#42a5f5", "SMA20"))
if "SMA 50" in indicators:
    series.append(_line_from(df["c"].rolling(50).mean(), "#fbbf24", "SMA50"))
if "EMA 9" in indicators:
    series.append(_line_from(df["c"].ewm(span=9, adjust=False).mean(), "#f472b6", "EMA9"))
if "Volume" in indicators:
    series.append(
        {
            "type": "Histogram",
            "data": volume,
            "options": {"priceFormat": {"type": "volume"}, "priceScaleId": ""},
            "priceScale": {"scaleMargins": {"top": 0.8, "bottom": 0}},
        }
    )

chart_options = {
    "height": 540,
    "layout": {"background": {"type": "solid", "color": "#0d1117"}, "textColor": "#d1d4dc"},
    "grid": {
        "vertLines": {"color": "rgba(197,203,206,0.10)"},
        "horzLines": {"color": "rgba(197,203,206,0.10)"},
    },
    "timeScale": {
        "timeVisible": True,
        "secondsVisible": False,
        "borderColor": "rgba(197,203,206,0.4)",
    },
    "rightPriceScale": {"borderColor": "rgba(197,203,206,0.4)"},
    "crosshair": {"mode": 1},
}


# --- Active-symbol panel + chart ---
q = get_quote(sym, asset_class)
delta_color = "#22c55e" if q["pct"] >= 0 else "#ef4444"
arrow = "▲" if q["pct"] >= 0 else "▼"

left, right = st.columns([2, 7])
with left:
    st.markdown(
        f"""
        <div class="price-panel">
            <div class="sym">{sym} · {interval}</div>
            <div class="px">${q['last']:,.2f}</div>
            <div class="delta" style="color: {delta_color};">{arrow} {q['pct']:+.2f}% · 24h</div>
            <div class="ohlc">
                High: <b>${q['high']:,.2f}</b><br/>
                Low: <b>${q['low']:,.2f}</b><br/>
                Volume: <b>{q['vol']:,.0f}</b>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with right:
    renderLightweightCharts(
        [{"chart": chart_options, "series": series}],
        key=f"chart_{sym}_{interval}",
    )

source_note = "Binance · real-time" if asset_class == "Crypto" else "Yahoo Finance · ~15 min delayed"
st.caption(
    f"Updated {time.strftime('%H:%M:%S')} · auto-refresh every {refresh_s}s · {source_note}"
)
