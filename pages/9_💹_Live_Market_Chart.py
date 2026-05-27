"""
Live market chart for crypto (Binance, real-time) and US stocks (yfinance, ~15min delayed).
TradingView Lightweight Charts for rendering. No API keys required.
"""
import time

import pandas as pd
import requests
import streamlit as st
import yfinance as yf
from streamlit_autorefresh import st_autorefresh
from streamlit_lightweight_charts import renderLightweightCharts

from tools.ui_theme import (
    apply_theme,
    chart_options,
    chart_shell_close,
    chart_shell_open,
    hero_header,
    section_header,
)

st.set_page_config(page_title="Live Market Chart", layout="wide")
apply_theme()

# Page-specific tweaks layered on top of the shared theme
st.markdown(
    """
    <style>
        /* Price panel for the active symbol */
        .price-panel {
            padding: 1.2rem 1.4rem;
            background: var(--glass-bg);
            border-radius: 16px;
            border: 1px solid var(--glass-border);
            height: 100%;
            backdrop-filter: blur(20px) saturate(180%);
            -webkit-backdrop-filter: blur(20px) saturate(180%);
            position: relative;
            overflow: hidden;
        }
        .price-panel::before {
            content: "";
            position: absolute; top: 0; left: 0; right: 0; height: 2px;
            background: linear-gradient(90deg, var(--accent-1), var(--accent-2));
            opacity: 0.7;
        }
        .price-panel .sym {
            font-size: 0.72rem; color: var(--text-3);
            letter-spacing: 0.12em; text-transform: uppercase;
            font-weight: 700;
        }
        .price-panel .px {
            font-size: 2.4rem; font-weight: 800;
            color: var(--text-1);
            margin-top: 0.4rem; line-height: 1;
            letter-spacing: -0.02em;
            font-feature-settings: "tnum" 1;
        }
        .price-panel .delta {
            font-size: 1rem; margin-top: 0.6rem; font-weight: 700;
            display: inline-flex; align-items: center; gap: 0.35rem;
            padding: 0.25rem 0.6rem;
            border-radius: 999px;
            border: 1px solid currentColor;
        }
        .price-panel .ohlc {
            margin-top: 1.1rem; padding-top: 0.9rem;
            border-top: 1px solid var(--glass-border);
            font-size: 0.85rem; color: var(--text-2); line-height: 1.7;
            font-feature-settings: "tnum" 1;
        }
        .price-panel .ohlc b { color: var(--text-1); font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)

hero_header(
    "💹 Live Market Chart",
    subtitle="Crypto from Binance (real-time) · Stocks from Yahoo Finance (~15 min delayed) · No API keys",
    chips=["Binance · Real-time", "Yahoo · Stocks", "TradingView Lightweight Charts"],
)


CRYPTO_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
STOCK_SYMBOLS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META", "SPY", "QQQ"]
# Indian market: indices first (Nifty 50, Sensex, Bank Nifty — the key F&O underlyings),
# then liquid equities. yfinance gives ~15 min delayed quotes in INR.
INDIA_SYMBOLS = [
    "^NSEI", "^BSESN", "^NSEBANK",
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", "SBIN.NS",
]
INDIA_LABEL = {
    "^NSEI": "NIFTY 50", "^BSESN": "SENSEX", "^NSEBANK": "BANKNIFTY",
}
CRYPTO_INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"]
STOCK_INTERVALS = ["1m", "5m", "15m", "30m", "1h", "1d"]
YF_PERIOD = {"1m": "5d", "5m": "1mo", "15m": "1mo", "30m": "1mo", "1h": "3mo", "1d": "2y"}

ASSET_CLASS_DEFAULTS = {
    "Crypto": (CRYPTO_SYMBOLS, CRYPTO_INTERVALS),
    "Stocks (US)": (STOCK_SYMBOLS, STOCK_INTERVALS),
    "India": (INDIA_SYMBOLS, STOCK_INTERVALS),
}
CURRENCY = {"Crypto": "$", "Stocks (US)": "$", "India": "₹"}


def _reset_symbol():
    new_class = st.session_state["asset_class"]
    syms, valid = ASSET_CLASS_DEFAULTS[new_class]
    st.session_state["symbol"] = syms[0]
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
    list(ASSET_CLASS_DEFAULTS.keys()),
    key="asset_class",
    on_change=_reset_symbol,
)
asset_class = asset_class or "Crypto"

symbols, intervals = ASSET_CLASS_DEFAULTS[asset_class]
ccy = CURRENCY[asset_class]


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
st.markdown(section_header("👁", "Watchlist · click a symbol to switch"), unsafe_allow_html=True)
cols = st.columns(len(symbols))
for i, sym in enumerate(symbols):
    with cols[i]:
        try:
            q = get_quote(sym, asset_class)
            marker = "● " if sym == st.session_state["symbol"] else ""
            label = INDIA_LABEL.get(sym, sym)
            st.metric(f"{marker}{label}", f"{ccy}{q['last']:,.2f}", f"{q['pct']:+.2f}%")
            if st.button("Select", key=f"sel_{sym}", use_container_width=True):
                st.session_state["symbol"] = sym
                st.rerun()
        except Exception:
            st.error(f"{sym} N/A")


# --- Controls ---
st.markdown(section_header("⚙", "View"), unsafe_allow_html=True)
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
        "color": "rgba(16,217,160,0.45)" if r.c >= r.o else "rgba(255,84,112,0.45)",
    }
    for r in df.itertuples()
]

series = [
    {
        "type": "Candlestick",
        "data": candles,
        "options": {
            "upColor": "#10d9a0",
            "downColor": "#ff5470",
            "borderVisible": False,
            "wickUpColor": "#10d9a0",
            "wickDownColor": "#ff5470",
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
    series.append(_line_from(df["c"].rolling(20).mean(), "#8b5cf6", "SMA20"))
if "SMA 50" in indicators:
    series.append(_line_from(df["c"].rolling(50).mean(), "#fbbf24", "SMA50"))
if "EMA 9" in indicators:
    series.append(_line_from(df["c"].ewm(span=9, adjust=False).mean(), "#ec4899", "EMA9"))
if "Volume" in indicators:
    series.append(
        {
            "type": "Histogram",
            "data": volume,
            "options": {"priceFormat": {"type": "volume"}, "priceScaleId": ""},
            "priceScale": {"scaleMargins": {"top": 0.8, "bottom": 0}},
        }
    )


# --- Active-symbol panel + chart ---
q = get_quote(sym, asset_class)
delta_color = "var(--pos)" if q["pct"] >= 0 else "var(--neg)"
arrow = "▲" if q["pct"] >= 0 else "▼"

left, right = st.columns([2, 7])
with left:
    st.markdown(
        f"""
        <div class="price-panel">
            <div class="sym">{INDIA_LABEL.get(sym, sym)} · {interval}</div>
            <div class="px">{ccy}{q['last']:,.2f}</div>
            <div class="delta" style="color: {delta_color};">{arrow} {q['pct']:+.2f}% · 24h</div>
            <div class="ohlc">
                High: <b>{ccy}{q['high']:,.2f}</b><br/>
                Low: <b>{ccy}{q['low']:,.2f}</b><br/>
                Volume: <b>{q['vol']:,.0f}</b>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with right:
    opts = chart_options(540)
    st.markdown(chart_shell_open(), unsafe_allow_html=True)
    renderLightweightCharts(
        [{"chart": opts, "series": series}],
        key=f"chart_{sym}_{interval}",
    )
    st.markdown(chart_shell_close(), unsafe_allow_html=True)

if asset_class == "Crypto":
    source_note = "Binance · real-time"
elif asset_class == "India":
    source_note = "Yahoo Finance · NSE/BSE · ~15 min delayed"
else:
    source_note = "Yahoo Finance · ~15 min delayed"
st.caption(
    f"Updated {time.strftime('%H:%M:%S')} · auto-refresh every {refresh_s}s · {source_note}"
)
