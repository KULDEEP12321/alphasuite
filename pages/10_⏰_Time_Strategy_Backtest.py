"""
Time-based intraday backtester for crypto.

Strategy template:
- At a "signal time" each day, note the price.
- At a "entry time" each day, enter long/short based on whether the price moved up or down since the signal time.
- Exit when stop-loss or take-profit (in price points / USD) is touched, walking forward through bars.
"""
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st
from streamlit_lightweight_charts import renderLightweightCharts

from tools.ui_theme import (
    apply_theme,
    area_series,
    chart_options,
    chart_shell_close,
    chart_shell_open,
    hero_header,
    result_panel,
    section_header,
)

st.set_page_config(page_title="Time Strategy Backtest", layout="wide")
apply_theme()

hero_header(
    "⏰ Time Strategy Backtest",
    subtitle="Daily entry at a fixed UTC time · long/short by recent momentum · fixed SL/TP in price points.",
    chips=["Binance · OHLCV", "Walk-forward simulation", "Compound · Fixed USD · Risk %"],
)


# ---------- Inputs ----------
st.markdown(section_header(1, "Strategy parameters"), unsafe_allow_html=True)
with st.container(border=True):
    c1, c2, c3, c4 = st.columns(4)
    symbol = c1.selectbox("Symbol", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"], 0)
    signal_time = c2.text_input("Signal time (UTC, HH:MM)", "09:30")
    entry_time = c3.text_input("Entry time (UTC, HH:MM)", "13:30")
    interval = c4.selectbox("Bar size", ["5m", "15m", "30m", "1h"], 1)

    c5, c6, c7, c8 = st.columns(4)
    sl_pts = c5.number_input("Stop loss (USD)", min_value=10.0, value=300.0, step=10.0)
    tp_pts = c6.number_input("Take profit (USD)", min_value=10.0, value=1000.0, step=10.0)
    init_cap = c7.number_input("Starting capital (USD)", min_value=10.0, value=1000.0, step=100.0)
    sizing = c8.selectbox(
        "Position sizing",
        ["Fixed USD per trade", "Compound (full capital each trade)", "Fixed risk per trade"],
        index=1,
        help="Fixed USD: same dollar amount each trade. Compound: each trade uses all current equity. Fixed risk: position size = (risk_$ / SL_$) × equity.",
    )
    if sizing == "Fixed USD per trade":
        pos_usd = st.number_input("USD per trade", min_value=1.0, value=200.0, step=10.0)
        risk_pct = None
    elif sizing == "Fixed risk per trade":
        pos_usd = None
        risk_pct = st.number_input("Risk % of equity per trade", min_value=0.1, max_value=20.0, value=1.0, step=0.1)
    else:
        pos_usd = None
        risk_pct = None

    c9, c10, c11 = st.columns([2, 2, 3])
    today = date.today()
    start_d = c9.date_input("Start date", value=today - timedelta(days=180), max_value=today - timedelta(days=1))
    end_d = c10.date_input("End date", value=today, max_value=today)
    c11.markdown(
        f"""
        <div style="padding-top: 1.4rem; color: var(--text-2); font-size: 0.85rem; line-height: 1.6;">
            Strategy: at <b style="color:var(--text-1);">{signal_time}</b> note price · at <b style="color:var(--text-1);">{entry_time}</b> go <b style="color: var(--pos);">LONG</b> if price rose, else <b style="color: var(--neg);">SHORT</b><br/>
            Risk: <b style="color:var(--text-1);">${sl_pts:.0f}</b> SL · Reward: <b style="color:var(--text-1);">${tp_pts:.0f}</b> TP · R:R = <b style="color:var(--text-1);">1:{tp_pts/sl_pts:.2f}</b>
        </div>
        """,
        unsafe_allow_html=True,
    )

run = st.button("🚀  Run backtest", type="primary", use_container_width=True)


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


def run_backtest(
    df: pd.DataFrame,
    sig_time: str,
    ent_time: str,
    sl_pts: float,
    tp_pts: float,
    sizing_mode: str,
    init_cap: float,
    pos_usd: float | None,
    risk_pct: float | None,
):
    """Walk through each date; enter at ent_time based on direction vs sig_time; exit on SL or TP."""
    trades = []
    equity = init_cap
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
            continue
        direction = "long" if ent_price > sig_price else "short"
        if direction == "long":
            sl, tp = ent_price - sl_pts, ent_price + tp_pts
        else:
            sl, tp = ent_price + sl_pts, ent_price - tp_pts

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
                exit_price, exit_reason, exit_dt = sl, "SL", row.dt
                break
            if hit_sl:
                exit_price, exit_reason, exit_dt = sl, "SL", row.dt
                break
            if hit_tp:
                exit_price, exit_reason, exit_dt = tp, "TP", row.dt
                break

        if exit_price is None:
            if len(forward):
                last = forward.iloc[-1]
                exit_price = float(last["c"])
                exit_dt = last["dt"]
            else:
                continue

        if sizing_mode == "Fixed USD per trade":
            stake_usd = pos_usd
        elif sizing_mode == "Compound (full capital each trade)":
            stake_usd = max(equity, 0)
        else:
            risk_dollar = equity * (risk_pct / 100.0)
            stake_usd = risk_dollar / sl_pts * ent_price
            stake_usd = min(stake_usd, equity)

        if stake_usd <= 0:
            break

        coins = stake_usd / ent_price
        if direction == "long":
            pnl = coins * (exit_price - ent_price)
        else:
            pnl = coins * (ent_price - exit_price)

        equity += pnl

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
                "stake_usd": stake_usd,
                "coins": coins,
                "pnl": pnl,
                "equity_after": equity,
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
        trades = run_backtest(
            df, signal_time, entry_time, sl_pts, tp_pts,
            sizing, init_cap, pos_usd, risk_pct,
        )

    if trades.empty:
        st.warning("No trades generated. The bar interval may not align with your entry/signal times.")
        st.stop()

    trades = trades.sort_values("entry_dt").reset_index(drop=True)
    trades["equity"] = trades["equity_after"]

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

    eq = trades["equity"].values
    peak = pd.Series(eq).cummax()
    dd = (eq - peak) / peak * 100
    max_dd = float(dd.min()) if len(dd) else 0
    pnl_pct = (total_pnl / init_cap) * 100 if init_cap else 0

    st.markdown(section_header(2, "Bottom line"), unsafe_allow_html=True)
    st.markdown(
        result_panel(
            final_eq=final_eq,
            init_cap=init_cap,
            total_pnl=total_pnl,
            pnl_pct=pnl_pct,
            meta=f"{symbol} {interval} · sizing {sizing} ·",
        ),
        unsafe_allow_html=True,
    )

    st.markdown(section_header("📊", "Details"), unsafe_allow_html=True)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Trades", f"{n}", f"{open_trades} open" if open_trades else None)
    m2.metric("Win rate", f"{win_rate:.1f}%", f"{wins}W / {losses}L")
    m3.metric("Max drawdown", f"{max_dd:.2f}%")
    expectancy = (win_rate / 100) * avg_win + (1 - win_rate / 100) * avg_loss if closed else 0
    m4.metric("Expectancy / trade", f"${expectancy:,.4f}")
    m5.metric(
        "Longs / Shorts",
        f"{(trades['direction']=='long').sum()} / {(trades['direction']=='short').sum()}",
    )

    # Equity curve
    st.markdown(section_header("📈", "Equity curve"), unsafe_allow_html=True)
    eq_data = [
        {"time": int(pd.Timestamp(r.entry_dt).timestamp()), "value": float(r.equity)}
        for r in trades.itertuples()
    ]
    accent = "#10d9a0" if total_pnl >= 0 else "#ff5470"

    st.markdown(chart_shell_open(), unsafe_allow_html=True)
    renderLightweightCharts(
        [{"chart": chart_options(420), "series": [area_series(eq_data, accent=accent)]}],
        key=f"eq_{symbol}_{start_d}_{end_d}",
    )
    st.markdown(chart_shell_close(), unsafe_allow_html=True)

    # Trade log
    st.markdown(section_header("📋", "Trade log"), unsafe_allow_html=True)
    pretty = trades.copy()
    pretty["entry_dt"] = pretty["entry_dt"].dt.strftime("%Y-%m-%d %H:%M")
    pretty["exit_dt"] = pretty["exit_dt"].dt.strftime("%Y-%m-%d %H:%M")
    for c in ["entry", "sl", "tp", "exit", "equity", "stake_usd"]:
        pretty[c] = pretty[c].round(2)
    pretty["pnl"] = pretty["pnl"].round(4)
    pretty = pretty.drop(columns=["coins", "date", "equity_after"])
    st.dataframe(pretty, use_container_width=True, hide_index=True)

    csv = pretty.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️  Download trade log (CSV)", csv, f"{symbol}_time_strategy.csv", "text/csv")
else:
    st.info("Set your parameters above and click **Run backtest**.")
