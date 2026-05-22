"""
Time-based intraday backtester for crypto.

Strategy template:
- At a "signal time" each day, note the price.
- At a "entry time" each day, enter long/short based on whether the price moved up or down since the signal time.
- Exit when stop-loss or take-profit (in price points / USD) is touched, walking forward through bars.
"""
from datetime import date, datetime, timedelta, timezone
import time
import requests
import pandas as pd
import streamlit as st
from streamlit_lightweight_charts import renderLightweightCharts

st.set_page_config(page_title="Time Strategy Backtest", layout="wide")

st.markdown(
    """
    <style>
        .block-container { padding-top: 1.5rem; }
        .ts-hero {
            background: linear-gradient(120deg, #064e3b 0%, #059669 60%, #10b981 100%);
            padding: 1.1rem 1.6rem;
            border-radius: 14px;
            margin-bottom: 1.25rem;
            color: white;
            box-shadow: 0 6px 24px rgba(16,185,129,0.18);
        }
        .ts-hero h1 { margin: 0; font-size: 1.7rem; font-weight: 700; }
        .ts-hero p { margin: 0.2rem 0 0 0; opacity: 0.85; font-size: 0.9rem; }
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
        }
        [data-testid="stMetricValue"] { font-size: 1.4rem !important; font-weight: 700; }
        [data-testid="stMetricLabel"] { font-size: 0.72rem !important; }
        [data-testid="stMetricDelta"] { font-size: 0.8rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="ts-hero">
        <h1>⏰ Time Strategy Backtest</h1>
        <p>Daily entry at a fixed UTC time · long/short by recent momentum · fixed SL/TP in price points</p>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------- Inputs ----------
with st.container(border=True):
    st.markdown('<div class="section-h">Strategy parameters</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    symbol = c1.selectbox("Symbol", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"], 0)
    signal_time = c2.text_input("Signal time (UTC, HH:MM)", "09:30")
    entry_time = c3.text_input("Entry time (UTC, HH:MM)", "13:30")
    interval = c4.selectbox("Bar size", ["5m", "15m", "30m", "1h"], 1)

    c5, c6, c7, c8 = st.columns(4)
    sl_pts = c5.number_input("Stop loss (USD)", min_value=10.0, value=300.0, step=10.0)
    tp_pts = c6.number_input("Take profit (USD)", min_value=10.0, value=1000.0, step=10.0)
    pos_usd = c7.number_input("Position size per trade (USD)", min_value=1.0, value=20.0, step=1.0)
    init_cap = c8.number_input("Starting capital (USD)", min_value=10.0, value=1000.0, step=100.0)

    c9, c10, c11 = st.columns([2, 2, 3])
    today = date.today()
    start_d = c9.date_input("Start date", value=today - timedelta(days=180), max_value=today - timedelta(days=1))
    end_d = c10.date_input("End date", value=today, max_value=today)
    c11.markdown(
        f"""
        <div style="padding-top: 1.4rem; color: #888; font-size: 0.85rem;">
            Strategy: at <b>{signal_time}</b> note price · at <b>{entry_time}</b> go <b style="color:#10b981;">LONG</b> if price rose, else <b style="color:#ef4444;">SHORT</b><br/>
            Risk: <b>${sl_pts:.0f}</b> SL · Reward: <b>${tp_pts:.0f}</b> TP · R:R = <b>1:{tp_pts/sl_pts:.2f}</b>
        </div>
        """,
        unsafe_allow_html=True,
    )

run = st.button("🚀 Run backtest", type="primary", use_container_width=True)


# ---------- Helpers ----------
INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Fetch all klines between start_ms and end_ms by paginating."""
    out = []
    cur = start_ms
    step_ms = INTERVAL_MS[interval]
    LIMIT = 1000
    while cur < end_ms:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "startTime": cur, "endTime": end_ms, "limit": LIMIT},
            timeout=15,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        out.extend(batch)
        if len(batch) < LIMIT:
            break
        cur = batch[-1][0] + step_ms
    df = pd.DataFrame(
        out, columns=["t", "o", "h", "l", "c", "v", "ct", "qv", "n", "tbb", "tbq", "i"]
    )
    df = df[["t", "o", "h", "l", "c", "v"]].astype({"t": "int64"})
    for col in ["o", "h", "l", "c", "v"]:
        df[col] = df[col].astype(float)
    df["dt"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df["date"] = df["dt"].dt.date
    df["hhmm"] = df["dt"].dt.strftime("%H:%M")
    return df.reset_index(drop=True)


def run_backtest(df: pd.DataFrame, sig_time: str, ent_time: str, sl_pts: float, tp_pts: float, pos_usd: float):
    """Walk through each date; enter at ent_time based on direction vs sig_time; exit on SL or TP."""
    trades = []
    daily_groups = df.groupby("date", sort=True)
    for d, day in daily_groups:
        sig_row = day[day["hhmm"] == sig_time]
        ent_row = day[day["hhmm"] == ent_time]
        if sig_row.empty or ent_row.empty:
            continue
        sig_price = float(sig_row.iloc[0]["o"])
        ent_idx = int(ent_row.iloc[0].name)
        ent_price = float(ent_row.iloc[0]["o"])
        if ent_price == sig_price:
            continue  # no direction signal
        direction = "long" if ent_price > sig_price else "short"
        if direction == "long":
            sl, tp = ent_price - sl_pts, ent_price + tp_pts
        else:
            sl, tp = ent_price + sl_pts, ent_price - tp_pts

        # Walk forward through subsequent bars
        forward = df.iloc[ent_idx + 1:]
        exit_price = None
        exit_reason = "OPEN"
        exit_dt = None
        for row in forward.itertuples():
            if direction == "long":
                hit_sl = row.l <= sl
                hit_tp = row.h >= tp
            else:
                hit_sl = row.h >= sl
                hit_tp = row.l <= tp
            if hit_sl and hit_tp:
                # Both touched in same bar — conservative: assume SL first
                exit_price, exit_reason, exit_dt = sl, "SL", row.dt
                break
            if hit_sl:
                exit_price, exit_reason, exit_dt = sl, "SL", row.dt
                break
            if hit_tp:
                exit_price, exit_reason, exit_dt = tp, "TP", row.dt
                break

        if exit_price is None:
            # Position never closed — mark with last available close
            if len(forward):
                last = forward.iloc[-1]
                exit_price = float(last["c"])
                exit_dt = last["dt"]
            else:
                continue

        coins = pos_usd / ent_price
        if direction == "long":
            pnl = coins * (exit_price - ent_price)
        else:
            pnl = coins * (ent_price - exit_price)

        trades.append(
            {
                "date": d,
                "direction": direction,
                "entry_dt": ent_row.iloc[0]["dt"],
                "entry": ent_price,
                "sl": sl,
                "tp": tp,
                "exit_dt": exit_dt,
                "exit": exit_price,
                "reason": exit_reason,
                "coins": coins,
                "pnl": pnl,
            }
        )
    return pd.DataFrame(trades)


# ---------- Run ----------
if run:
    start_ms = int(datetime.combine(start_d, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime.combine(end_d, datetime.max.time()).replace(tzinfo=timezone.utc).timestamp() * 1000)

    with st.spinner(f"Fetching {interval} candles for {symbol} ({start_d} → {end_d})…"):
        df = fetch_klines(symbol, interval, start_ms, end_ms)

    if df.empty:
        st.error("No data returned. Try a smaller date range or a different symbol.")
        st.stop()

    st.caption(f"Fetched {len(df):,} bars · {df['dt'].min()} → {df['dt'].max()}")

    with st.spinner("Running backtest…"):
        trades = run_backtest(df, signal_time, entry_time, sl_pts, tp_pts, pos_usd)

    if trades.empty:
        st.warning("No trades generated. The bar interval may not align with your entry/signal times.")
        st.stop()

    trades = trades.sort_values("entry_dt").reset_index(drop=True)
    trades["equity"] = init_cap + trades["pnl"].cumsum()

    # ---------- Summary metrics ----------
    n = len(trades)
    wins = (trades["reason"] == "TP").sum()
    losses = (trades["reason"] == "SL").sum()
    open_trades = (trades["reason"] == "OPEN").sum()
    closed = wins + losses
    win_rate = (wins / closed * 100) if closed else 0
    total_pnl = trades["pnl"].sum()
    final_eq = init_cap + total_pnl
    avg_win = trades.loc[trades["reason"] == "TP", "pnl"].mean() if wins else 0
    avg_loss = trades.loc[trades["reason"] == "SL", "pnl"].mean() if losses else 0

    # Max drawdown
    eq = trades["equity"].values
    peak = pd.Series(eq).cummax()
    dd = (eq - peak) / peak * 100
    max_dd = dd.min() if len(dd) else 0

    st.markdown('<div class="section-h">Results</div>', unsafe_allow_html=True)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Trades", f"{n}", f"{open_trades} open")
    m2.metric("Win rate", f"{win_rate:.1f}%", f"{wins}W / {losses}L")
    m3.metric("Total PnL", f"${total_pnl:,.2f}", f"{total_pnl/init_cap*100:+.2f}%")
    m4.metric("Final equity", f"${final_eq:,.2f}")
    m5.metric("Max drawdown", f"{max_dd:.2f}%")

    m6, m7, m8, m9 = st.columns(4)
    m6.metric("Avg win", f"${avg_win:,.4f}")
    m7.metric("Avg loss", f"${avg_loss:,.4f}" if losses else "—")
    expectancy = (win_rate / 100) * avg_win + (1 - win_rate / 100) * avg_loss if closed else 0
    m8.metric("Expectancy / trade", f"${expectancy:,.4f}")
    m9.metric(
        "Longs / Shorts",
        f"{(trades['direction']=='long').sum()} / {(trades['direction']=='short').sum()}",
    )

    # ---------- Equity curve ----------
    st.markdown('<div class="section-h">Equity curve</div>', unsafe_allow_html=True)
    eq_data = [
        {"time": int(pd.Timestamp(r.entry_dt).timestamp()), "value": float(r.equity)}
        for r in trades.itertuples()
    ]
    chart_options = {
        "height": 380,
        "layout": {"background": {"type": "solid", "color": "#0d1117"}, "textColor": "#d1d4dc"},
        "grid": {
            "vertLines": {"color": "rgba(197,203,206,0.10)"},
            "horzLines": {"color": "rgba(197,203,206,0.10)"},
        },
        "timeScale": {"timeVisible": True, "secondsVisible": False, "borderColor": "rgba(197,203,206,0.4)"},
        "rightPriceScale": {"borderColor": "rgba(197,203,206,0.4)"},
    }
    series = [
        {
            "type": "Area",
            "data": eq_data,
            "options": {
                "topColor": "rgba(16,185,129,0.35)",
                "bottomColor": "rgba(16,185,129,0.02)",
                "lineColor": "#10b981",
                "lineWidth": 2,
            },
        }
    ]
    renderLightweightCharts([{"chart": chart_options, "series": series}], key=f"eq_{symbol}_{start_d}_{end_d}")

    # ---------- Trade log ----------
    st.markdown('<div class="section-h">Trade log</div>', unsafe_allow_html=True)
    pretty = trades.copy()
    pretty["entry_dt"] = pretty["entry_dt"].dt.strftime("%Y-%m-%d %H:%M")
    pretty["exit_dt"] = pretty["exit_dt"].dt.strftime("%Y-%m-%d %H:%M")
    pretty["entry"] = pretty["entry"].round(2)
    pretty["sl"] = pretty["sl"].round(2)
    pretty["tp"] = pretty["tp"].round(2)
    pretty["exit"] = pretty["exit"].round(2)
    pretty["pnl"] = pretty["pnl"].round(4)
    pretty["equity"] = pretty["equity"].round(4)
    pretty = pretty.drop(columns=["coins", "date"])
    st.dataframe(pretty, use_container_width=True, hide_index=True)

    csv = pretty.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download trade log (CSV)", csv, f"{symbol}_time_strategy.csv", "text/csv")
else:
    st.info("Set your parameters above and click **Run backtest**.")
