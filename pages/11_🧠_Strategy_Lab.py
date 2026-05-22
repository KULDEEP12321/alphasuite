"""
Strategy Lab: write a trading strategy in natural language, an LLM parses it
into a structured DSL, and the platform runs a historical backtest.
"""
import json
import os
import time
from datetime import date, datetime, timedelta, timezone

import streamlit as st
from dotenv import load_dotenv
from streamlit_lightweight_charts import renderLightweightCharts

from tools.strategy_lab import (
    fetch_klines,
    parse_strategy,
    run_backtest,
    validate_strategy,
)

load_dotenv()

st.set_page_config(page_title="Strategy Lab", layout="wide")

st.markdown(
    """
    <style>
        .block-container { padding-top: 1.5rem; }
        .lab-hero {
            background: linear-gradient(120deg, #312e81 0%, #6d28d9 60%, #c026d3 100%);
            padding: 1.1rem 1.6rem;
            border-radius: 14px;
            margin-bottom: 1.25rem;
            color: white;
            box-shadow: 0 6px 24px rgba(109,40,217,0.18);
        }
        .lab-hero h1 { margin: 0; font-size: 1.7rem; font-weight: 700; }
        .lab-hero p { margin: 0.2rem 0 0 0; opacity: 0.85; font-size: 0.9rem; }
        .section-h {
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: #888;
            margin: 1.1rem 0 0.4rem 0;
            font-weight: 600;
        }
        [data-testid="stMetricValue"] { font-size: 1.4rem !important; font-weight: 700; }
        [data-testid="stMetricLabel"] { font-size: 0.72rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="lab-hero">
        <h1>🧠 Strategy Lab</h1>
        <p>Write a strategy in plain English · LLM parses it · we run the backtest</p>
    </div>
    """,
    unsafe_allow_html=True,
)


EXAMPLES = {
    "Time-based BTC (your original)": (
        "At 13:30 UTC on BTCUSDT, look at the price change since 09:30 UTC. "
        "If price rose, go long; if price fell, go short. "
        "Use a 300 USD stop loss and 1000 USD take profit. "
        "Start with $1000 capital and compound."
    ),
    "MA crossover, always-direction": (
        "On ETHUSDT 1h, buy when the 9-period moving average crosses above the 21-period MA. "
        "Sell when it crosses below. Stop loss 2%, take profit 5%. "
        "$1000 starting capital, risk 1% per trade."
    ),
    "RSI mean reversion": (
        "On BTCUSDT 15m, buy when RSI(14) drops below 25 and sell when RSI rises above 75. "
        "Stop loss 1.5%, take profit 3%. Start $1000, compound."
    ),
    "Donchian breakout": (
        "On SOLUSDT 1h, when price breaks above the 20-bar high go long; "
        "below the 20-bar low go short. SL 3%, TP 9%. $1000 compound."
    ),
}


# ---------- Session state ----------
if "spec" not in st.session_state:
    st.session_state.spec = None
if "spec_text" not in st.session_state:
    st.session_state.spec_text = ""
if "trades" not in st.session_state:
    st.session_state.trades = None
if "df_meta" not in st.session_state:
    st.session_state.df_meta = None


# ---------- Step 1: Describe ----------
st.markdown('<div class="section-h">1 · Describe your strategy</div>', unsafe_allow_html=True)
c1, c2 = st.columns([3, 2])
with c1:
    example_pick = st.selectbox("Load an example (optional)", ["—"] + list(EXAMPLES.keys()))
    if example_pick != "—" and st.session_state.get("loaded_example") != example_pick:
        st.session_state.loaded_example = example_pick
        st.session_state.spec_text = EXAMPLES[example_pick]
    text = st.text_area(
        "Plain-English strategy description",
        value=st.session_state.spec_text,
        height=170,
        placeholder="e.g. On BTCUSDT 1h, buy when 9-period MA crosses above 21-period MA. SL 2%, TP 5%. $1000 starting capital, compound.",
    )
    st.session_state.spec_text = text

with c2:
    st.markdown(
        """
        <div style="background: rgba(255,255,255,0.025); border: 1px solid rgba(255,255,255,0.07); border-radius: 12px; padding: 0.9rem 1.1rem; color: #aaa; font-size: 0.83rem; line-height: 1.55;">
            <b style="color:#ddd;">Supported primitives:</b><br/>
            • <b>Time entry</b> — at a UTC time, daily<br/>
            • <b>MA crossover</b> — fast/slow periods<br/>
            • <b>RSI threshold</b> — oversold/overbought<br/>
            • <b>Breakout</b> — N-bar high/low break<br/><br/>
            <b style="color:#ddd;">Exits:</b> SL & TP in points (USD) or %.<br/>
            <b style="color:#ddd;">Sizing:</b> compound, fixed USD, or fixed risk %.<br/>
            <b style="color:#ddd;">Symbols:</b> BTC, ETH, SOL, BNB, XRP, DOGE, ADA (USDT pairs).
        </div>
        """,
        unsafe_allow_html=True,
    )

if st.button("🪄 Parse with LLM", type="primary", use_container_width=True, disabled=not text.strip()):
    if not os.getenv("GROQ_API_KEY"):
        st.error("GROQ_API_KEY missing from .env")
    else:
        try:
            with st.spinner("Asking Groq to parse the strategy…"):
                t0 = time.time()
                spec = parse_strategy(text)
                dt = time.time() - t0
            errs = validate_strategy(spec)
            if errs:
                st.error("Parsed JSON but it has issues:")
                for e in errs:
                    st.write(f"• {e}")
                st.session_state.spec = spec  # still surface it for inspection
            else:
                st.success(f"Parsed in {dt:.1f}s — review and edit below if needed.")
                st.session_state.spec = spec
                st.session_state.trades = None
        except Exception as e:
            st.error(f"Parse failed: {e}")


# ---------- Step 2: Review / edit ----------
if st.session_state.spec:
    st.markdown('<div class="section-h">2 · Review the parsed spec</div>', unsafe_allow_html=True)
    edited = st.text_area(
        "Strategy JSON (editable)",
        value=json.dumps(st.session_state.spec, indent=2),
        height=320,
        label_visibility="collapsed",
    )
    try:
        st.session_state.spec = json.loads(edited)
        errs = validate_strategy(st.session_state.spec)
        if errs:
            st.warning("Validation issues:\n" + "\n".join(f"• {e}" for e in errs))
    except json.JSONDecodeError as e:
        st.error(f"Invalid JSON: {e}")

    # Date range
    cdate1, cdate2 = st.columns(2)
    today = date.today()
    start_d = cdate1.date_input("Backtest start", value=today - timedelta(days=180))
    end_d = cdate2.date_input("Backtest end", value=today)

    if st.button("🚀 Run backtest", type="primary", use_container_width=True):
        spec = st.session_state.spec
        errs = validate_strategy(spec)
        if errs:
            st.error("Fix validation errors first.")
        else:
            start_ms = int(datetime.combine(start_d, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp() * 1000)
            end_ms = int(datetime.combine(end_d, datetime.max.time()).replace(tzinfo=timezone.utc).timestamp() * 1000)
            try:
                with st.spinner(f"Fetching {spec['symbol']} {spec['interval']} bars…"):
                    df = fetch_klines(spec["symbol"], spec["interval"], start_ms, end_ms)
                if df.empty:
                    st.error("No data fetched. Try a wider range or different symbol.")
                else:
                    with st.spinner("Running backtest…"):
                        trades = run_backtest(spec, df)
                    st.session_state.trades = trades
                    st.session_state.df_meta = {"bars": len(df), "start": df["dt"].min(), "end": df["dt"].max()}
            except Exception as e:
                st.error(f"Backtest failed: {e}")


# ---------- Step 3: Results ----------
trades = st.session_state.trades
if trades is not None and len(trades):
    spec = st.session_state.spec
    init_cap = float(spec["capital"])
    n = len(trades)
    wins = (trades["reason"] == "TP").sum()
    losses = (trades["reason"] == "SL").sum()
    open_trades = (trades["reason"] == "OPEN").sum()
    closed = wins + losses
    win_rate = (wins / closed * 100) if closed else 0
    total_pnl = trades["pnl"].sum()
    final_eq = init_cap + total_pnl
    pnl_pct = (total_pnl / init_cap) * 100 if init_cap else 0
    avg_win = trades.loc[trades["reason"] == "TP", "pnl"].mean() if wins else 0
    avg_loss = trades.loc[trades["reason"] == "SL", "pnl"].mean() if losses else 0
    eq = trades["equity_after"].values
    peak = (trades["equity_after"].cummax()).values
    dd = (eq - peak) / peak * 100
    max_dd = float(dd.min()) if len(dd) else 0
    is_win = total_pnl >= 0
    sign = "+" if total_pnl >= 0 else ""
    hero_color = "#10b981" if is_win else "#ef4444"
    hero_bg = "rgba(16,185,129,0.08)" if is_win else "rgba(239,68,68,0.08)"
    hero_border = "rgba(16,185,129,0.4)" if is_win else "rgba(239,68,68,0.4)"

    st.markdown('<div class="section-h">3 · Results</div>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div style="
            background: {hero_bg};
            border: 1px solid {hero_border};
            border-radius: 16px;
            padding: 1.5rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
        ">
            <div>
                <div style="font-size: 0.75rem; color: #888; letter-spacing: 0.1em; text-transform: uppercase; font-weight: 600;">Final equity</div>
                <div style="font-size: 3rem; font-weight: 800; color: white; line-height: 1; margin-top: 0.35rem;">${final_eq:,.2f}</div>
                <div style="margin-top: 0.5rem; color: #aaa; font-size: 0.9rem;">
                    {spec.get('name','Strategy')} · {spec['symbol']} · {spec['interval']} · started <b style="color:#ccc;">${init_cap:,.2f}</b>
                </div>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 0.75rem; color: #888; letter-spacing: 0.1em; text-transform: uppercase; font-weight: 600;">Net P&amp;L</div>
                <div style="font-size: 2.2rem; font-weight: 800; color: {hero_color}; line-height: 1; margin-top: 0.35rem;">{sign}${total_pnl:,.2f}</div>
                <div style="margin-top: 0.5rem; font-size: 1.1rem; color: {hero_color}; font-weight: 600;">{sign}{pnl_pct:.2f}%</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Trades", f"{n}", f"{open_trades} open")
    m2.metric("Win rate", f"{win_rate:.1f}%", f"{wins}W / {losses}L")
    m3.metric("Max drawdown", f"{max_dd:.2f}%")
    expectancy = (win_rate / 100) * avg_win + (1 - win_rate / 100) * avg_loss if closed else 0
    m4.metric("Expectancy / trade", f"${expectancy:,.4f}")
    m5.metric("Longs / Shorts", f"{(trades['direction']=='long').sum()} / {(trades['direction']=='short').sum()}")

    # Equity curve
    st.markdown('<div class="section-h">Equity curve</div>', unsafe_allow_html=True)
    eq_data = [{"time": int(t.timestamp()), "value": float(v)} for t, v in zip(trades["entry_dt"], trades["equity_after"])]
    renderLightweightCharts(
        [{
            "chart": {
                "height": 380,
                "layout": {"background": {"type": "solid", "color": "#0d1117"}, "textColor": "#d1d4dc"},
                "grid": {"vertLines": {"color": "rgba(197,203,206,0.10)"}, "horzLines": {"color": "rgba(197,203,206,0.10)"}},
                "timeScale": {"timeVisible": True, "secondsVisible": False, "borderColor": "rgba(197,203,206,0.4)"},
                "rightPriceScale": {"borderColor": "rgba(197,203,206,0.4)"},
            },
            "series": [{
                "type": "Area",
                "data": eq_data,
                "options": {
                    "topColor": "rgba(192,38,211,0.35)",
                    "bottomColor": "rgba(192,38,211,0.02)",
                    "lineColor": "#c026d3",
                    "lineWidth": 2,
                },
            }],
        }],
        key=f"eq_{spec['symbol']}_{spec['interval']}",
    )

    # Trade log
    st.markdown('<div class="section-h">Trade log</div>', unsafe_allow_html=True)
    show = trades.copy()
    show["entry_dt"] = show["entry_dt"].dt.strftime("%Y-%m-%d %H:%M")
    show["exit_dt"] = show["exit_dt"].dt.strftime("%Y-%m-%d %H:%M")
    for c in ["entry", "sl", "tp", "exit", "stake_usd", "equity_after"]:
        show[c] = show[c].round(2)
    show["pnl"] = show["pnl"].round(4)
    st.dataframe(show, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇️ Download trade log (CSV)",
        show.to_csv(index=False).encode("utf-8"),
        f"{spec.get('name','strategy').replace(' ','_')}.csv",
        "text/csv",
    )
elif trades is not None:
    st.warning("No trades generated. Check your entry/exit logic.")
