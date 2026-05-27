"""
NSE Option Chain — live strike grid, PCR, max pain.

Data source: Sensibull's free public endpoint (one call returns the full
chain — every strike × every expiry × {CE, PE} — with LTP/Vol/OI).

NSE's own /api/option-chain-* endpoints have been shadow-blocked since 2025
(200 OK with empty {} body for non-browser sessions), even with TLS
fingerprinting (curl_cffi/nsepython). Sensibull's API does not require auth
or session warm-up and uses Chrome TLS impersonation transparently.

Limitations vs. paid feeds: no IV (implied volatility) and no change-in-OI.
PCR and max pain are derivable from OI alone and are shown.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
from curl_cffi import requests as cffi

from tools.ui_theme import apply_theme, hero_header, section_header

st.set_page_config(page_title="Option Chain", layout="wide")
apply_theme()

hero_header(
    "⛓ Option Chain",
    subtitle="Live NSE option chain · CE/PE strike grid with LTP, Vol, OI · auto PCR and max pain.",
    chips=["Sensibull · live", "Indices + Equities", "PCR · Max Pain"],
)

INDEX_SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
EQUITY_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN",
    "AXISBANK", "KOTAKBANK", "ITC", "HINDUNILVR", "BAJFINANCE", "LT",
]

# yfinance proxy for the underlying spot price (Sensibull doesn't expose it cleanly).
SPOT_TICKER = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
    "MIDCPNIFTY": "NIFTY_MID_SELECT.NS",
}


@st.cache_resource(ttl=600, show_spinner=False)
def _http() -> cffi.Session:
    return cffi.Session(impersonate="chrome120")


@st.cache_data(ttl=20, show_spinner=False)
def fetch_instruments(symbol: str) -> list[dict]:
    """Single call returns the full chain for the symbol — every expiry, every strike."""
    s = _http()
    r = s.get(f"https://api.sensibull.com/v1/instruments/{symbol}", timeout=15)
    r.raise_for_status()
    body = r.json()
    if not body.get("status") or "data" not in body:
        raise RuntimeError(f"Unexpected response: {str(body)[:200]}")
    return body["data"]


@st.cache_data(ttl=60, show_spinner=False)
def fetch_spot(symbol: str) -> float:
    """Get the underlying spot price. Indices via ^NSEI/^NSEBANK, equities via SYMBOL.NS."""
    yf_sym = SPOT_TICKER.get(symbol, f"{symbol}.NS")
    info = yf.Ticker(yf_sym).fast_info
    return float(info.get("lastPrice") or 0)


def to_chain_df(instruments: list[dict], expiry: str) -> pd.DataFrame:
    """Flatten Sensibull instruments → one row per strike with CE and PE side by side."""
    by_strike: dict[float, dict] = {}
    for it in instruments:
        if it.get("segment") != "NFO-OPT" or it.get("expiry") != expiry:
            continue
        strike = float(it["strike"])
        side = it["instrument_type"]  # "CE" or "PE"
        prefix = side.lower()
        row = by_strike.setdefault(strike, {"strike": strike})
        row[f"{prefix}_ltp"] = float(it.get("last_price") or 0)
        row[f"{prefix}_vol"] = int(it.get("volume") or 0)
        row[f"{prefix}_oi"] = int(it.get("oi") or 0)
    df = pd.DataFrame(by_strike.values())
    if df.empty:
        return df
    # Ensure both sides are present even if one side has no instrument
    for col in ["ce_ltp", "ce_vol", "ce_oi", "pe_ltp", "pe_vol", "pe_oi"]:
        if col not in df.columns:
            df[col] = 0
    return df[["ce_ltp", "ce_vol", "ce_oi", "strike", "pe_oi", "pe_vol", "pe_ltp"]].sort_values("strike").reset_index(drop=True)


def compute_max_pain(df: pd.DataFrame) -> int:
    """Strike that minimises total option-writer payout at expiry."""
    strikes = df["strike"].values
    ce_oi = df["ce_oi"].values
    pe_oi = df["pe_oi"].values
    best_strike, best_loss = int(strikes[0]), float("inf")
    for k in strikes:
        ce_loss = ((k - strikes).clip(min=0) * ce_oi).sum()
        pe_loss = ((strikes - k).clip(min=0) * pe_oi).sum()
        total = ce_loss + pe_loss
        if total < best_loss:
            best_loss = total
            best_strike = int(k)
    return best_strike


def style_chain(df: pd.DataFrame, atm: int, spot: float):
    """ATM row highlighted, ITM cells shaded by side."""
    ce_cols = ["ce_ltp", "ce_vol", "ce_oi"]
    pe_cols = ["pe_oi", "pe_vol", "pe_ltp"]

    def row_bg(row):
        styles = [""] * len(row)
        if int(row["strike"]) == atm:
            styles = ["background-color: rgba(139,92,246,0.18); font-weight: 700;"] * len(row)
        if row["strike"] < spot:
            for c in ce_cols:
                styles[list(row.index).index(c)] += " background-color: rgba(16,217,160,0.06);"
        if row["strike"] > spot:
            for c in pe_cols:
                styles[list(row.index).index(c)] += " background-color: rgba(255,84,112,0.06);"
        return styles

    fmt = {
        "ce_ltp": "{:,.2f}", "ce_vol": "{:,.0f}", "ce_oi": "{:,.0f}",
        "strike": "{:,.0f}",
        "pe_oi": "{:,.0f}", "pe_vol": "{:,.0f}", "pe_ltp": "{:,.2f}",
    }
    return df.style.apply(row_bg, axis=1).format(fmt)


# ───────────────────────── UI ─────────────────────────
sym_class = st.segmented_control("Underlying type", ["Index", "Equity"], default="Index")
sym_class = sym_class or "Index"
symbols = INDEX_SYMBOLS if sym_class == "Index" else EQUITY_SYMBOLS

c1, c2, c3 = st.columns([2, 2, 2])
symbol = c1.selectbox("Symbol", symbols, key="oc_symbol")

try:
    with st.spinner(f"Fetching {symbol} option chain…"):
        instruments = fetch_instruments(symbol)
        spot = fetch_spot(symbol)
except Exception as e:
    st.error(f"Failed to fetch: {e}")
    st.stop()

# Distinct expiries, sorted
expiries = sorted({
    it["expiry"] for it in instruments
    if it.get("segment") == "NFO-OPT" and it.get("expiry")
})
if not expiries:
    st.warning(f"No option-chain expiries returned for {symbol}.")
    st.stop()

expiry = c2.selectbox("Expiry", expiries, key="oc_expiry")
n_strikes = c3.slider("Strikes around ATM", 5, 30, 15)

df = to_chain_df(instruments, expiry)
if df.empty:
    st.warning("No strikes for this expiry.")
    st.stop()

# ATM = closest strike to spot
atm_pos = (df["strike"] - spot).abs().idxmin()
atm = int(df.loc[atm_pos, "strike"])
lo = max(0, atm_pos - n_strikes)
hi = min(len(df), atm_pos + n_strikes + 1)
window = df.iloc[lo:hi].copy()

# Summary stats over the full chain
total_ce_oi = float(df["ce_oi"].sum())
total_pe_oi = float(df["pe_oi"].sum())
pcr = total_pe_oi / total_ce_oi if total_ce_oi else 0
max_pain = compute_max_pain(df)
max_ce_oi_strike = int(df.loc[df["ce_oi"].idxmax(), "strike"])
max_pe_oi_strike = int(df.loc[df["pe_oi"].idxmax(), "strike"])

# ───────────────────────── Summary panel ─────────────────────────
st.markdown(section_header("📊", f"{symbol} · {expiry}"), unsafe_allow_html=True)

bias_is_bull = pcr > 1
bias_color = "#10d9a0" if bias_is_bull else "#ff5470"
bias_glow = "16,217,160" if bias_is_bull else "255,84,112"
bias_label = "Bullish skew (PCR > 1)" if bias_is_bull else "Bearish skew (PCR ≤ 1)"

st.markdown(
    f"""
    <div style="
        position: relative;
        background:
            radial-gradient(ellipse 60% 80% at 0% 50%, rgba({bias_glow},0.18), transparent 70%),
            radial-gradient(ellipse 50% 70% at 100% 50%, rgba(139,92,246,0.14), transparent 70%),
            rgba(255,255,255,0.025);
        border: 1px solid rgba({bias_glow},0.35);
        border-radius: 22px;
        padding: 1.8rem 2.2rem;
        margin-bottom: 1.2rem;
        backdrop-filter: blur(24px) saturate(200%);
        -webkit-backdrop-filter: blur(24px) saturate(200%);
        box-shadow: 0 20px 60px rgba(0,0,0,0.4), 0 0 80px rgba({bias_glow},0.12);
        overflow: hidden;
    ">
        <div style="display: flex; justify-content: space-between; align-items: flex-end; gap: 2rem;">
            <div>
                <div style="font-size: 0.7rem; color: #71717a; letter-spacing: 0.16em; text-transform: uppercase; font-weight: 700; margin-bottom: 0.5rem;">
                    ✦ Spot
                </div>
                <div style="font-size: 3.6rem; font-weight: 800; line-height: 0.95; letter-spacing: -0.03em;
                            background: linear-gradient(120deg, #fff 0%, {bias_color} 100%);
                            -webkit-background-clip: text; background-clip: text; color: transparent;
                            font-feature-settings: 'tnum' 1;">
                    ₹{spot:,.2f}
                </div>
                <div style="margin-top: 0.6rem; color: #a1a1aa; font-size: 0.92rem; font-weight: 500;">
                    ATM <span style="color:#fafafa; font-weight:700;">{atm:,}</span>
                    · {bias_label}
                </div>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 0.7rem; color: #71717a; letter-spacing: 0.16em; text-transform: uppercase; font-weight: 700; margin-bottom: 0.5rem;">
                    PCR
                </div>
                <div style="font-size: 2.4rem; font-weight: 800; color: {bias_color}; line-height: 0.95; letter-spacing: -0.02em; font-feature-settings: 'tnum' 1;">
                    {pcr:.2f}
                </div>
                <div style="margin-top: 0.5rem; font-size: 0.85rem; color: var(--text-2);">
                    Max pain <b style="color:#fafafa;">{max_pain:,}</b>
                </div>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total CE OI", f"{total_ce_oi:,.0f}")
m2.metric("Total PE OI", f"{total_pe_oi:,.0f}")
m3.metric("Max PE OI (support)", f"{max_pe_oi_strike:,}")
m4.metric("Max CE OI (resistance)", f"{max_ce_oi_strike:,}")
m5.metric("Spot − ATM", f"{spot - atm:+,.2f}")

# ───────────────────────── Chain table ─────────────────────────
st.markdown(section_header("⛓", f"Strike grid · ±{n_strikes} around ATM"), unsafe_allow_html=True)

st.markdown(
    """
    <div style="font-size: 0.78rem; color: var(--text-2); margin-bottom: 0.4rem;">
        <span style="background: rgba(16,217,160,0.18); padding: 2px 8px; border-radius: 4px; color: var(--text-1);">CE ITM</span>
        &nbsp;left half ·
        <span style="background: rgba(255,84,112,0.18); padding: 2px 8px; border-radius: 4px; color: var(--text-1);">PE ITM</span>
        &nbsp;right half ·
        <span style="background: rgba(139,92,246,0.25); padding: 2px 8px; border-radius: 4px; color: var(--text-1);">ATM row</span>
    </div>
    """,
    unsafe_allow_html=True,
)

st.dataframe(
    style_chain(window, atm, spot),
    use_container_width=True,
    hide_index=True,
    column_config={
        "ce_ltp": st.column_config.NumberColumn("LTP"),
        "ce_vol": st.column_config.NumberColumn("Vol"),
        "ce_oi": st.column_config.NumberColumn("OI"),
        "strike": st.column_config.NumberColumn("STRIKE"),
        "pe_oi": st.column_config.NumberColumn("OI"),
        "pe_vol": st.column_config.NumberColumn("Vol"),
        "pe_ltp": st.column_config.NumberColumn("LTP"),
    },
)

st.caption(
    "Calls (CE) on the left · Strike in the middle · Puts (PE) on the right. "
    "Data: Sensibull (free, no auth) · cached 20s · refresh by interaction. "
    f"PCR = total PE OI ÷ total CE OI = {pcr:.3f}. "
    "IV and change-in-OI need a paid feed and are not shown."
)


# ───────────────────────── OI build-up across expiries ─────────────────────────
def build_oi_pivots(
    insts: list[dict],
    expiries_subset: list[str],
    atm_strike: float,
    n_around: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (CE pivot, PE pivot): rows = strikes, columns = expiries, values = OI."""
    rows = []
    for it in insts:
        if it.get("segment") != "NFO-OPT":
            continue
        if it.get("expiry") not in expiries_subset:
            continue
        rows.append({
            "strike": float(it["strike"]),
            "expiry": it["expiry"],
            "side": it["instrument_type"],
            "oi": int(it.get("oi") or 0),
        })
    if not rows:
        return pd.DataFrame(), pd.DataFrame()
    long = pd.DataFrame(rows)

    def _pivot(side: str) -> pd.DataFrame:
        p = (long[long["side"] == side]
             .pivot_table(index="strike", columns="expiry", values="oi", aggfunc="sum")
             .fillna(0).astype(int))
        if p.empty:
            return p
        all_strikes = sorted(p.index.tolist())
        atm_pos = min(range(len(all_strikes)), key=lambda i: abs(all_strikes[i] - atm_strike))
        lo = all_strikes[max(0, atm_pos - n_around)]
        hi = all_strikes[min(len(all_strikes) - 1, atm_pos + n_around)]
        p = p.loc[(p.index >= lo) & (p.index <= hi)]
        # Order columns by expiry date (ISO strings sort correctly)
        return p.reindex(columns=sorted(p.columns))

    return _pivot("CE"), _pivot("PE")


st.markdown(section_header("🌐", "OI build-up across expiries"), unsafe_allow_html=True)

n_exp = st.slider(
    "Expiries to compare",
    min_value=2, max_value=min(8, len(expiries)),
    value=min(4, len(expiries)),
)
chosen_expiries = expiries[:n_exp]

ce_pivot, pe_pivot = build_oi_pivots(instruments, chosen_expiries, atm, n_strikes)

# Per-expiry totals — quick read on where the action is
totals = []
for exp in chosen_expiries:
    ce_t = int(ce_pivot[exp].sum()) if exp in ce_pivot.columns else 0
    pe_t = int(pe_pivot[exp].sum()) if exp in pe_pivot.columns else 0
    totals.append({"expiry": exp, "CE OI": ce_t, "PE OI": pe_t, "PCR": round(pe_t / ce_t, 2) if ce_t else 0})
totals_df = pd.DataFrame(totals).set_index("expiry")

tcol1, tcol2 = st.columns([3, 2])
with tcol1:
    st.markdown("**Total OI per expiry (windowed strikes only)**")
    st.bar_chart(totals_df[["CE OI", "PE OI"]], color=["#10d9a0", "#ff5470"], height=240)
with tcol2:
    st.markdown("**Per-expiry summary**")
    st.dataframe(
        totals_df.style.format({"CE OI": "{:,}", "PE OI": "{:,}", "PCR": "{:.2f}"}),
        use_container_width=True,
    )

# Heatmaps: strike × expiry intensity, CE green, PE red
hcol1, hcol2 = st.columns(2)
with hcol1:
    st.markdown("**Call (CE) OI · strike × expiry**")
    if ce_pivot.empty:
        st.info("No CE data for the chosen expiries.")
    else:
        st.dataframe(
            ce_pivot.style
                .background_gradient(cmap="Greens", axis=None)
                .format("{:,}"),
            use_container_width=True,
            height=min(560, 38 * (len(ce_pivot) + 1)),
        )
with hcol2:
    st.markdown("**Put (PE) OI · strike × expiry**")
    if pe_pivot.empty:
        st.info("No PE data for the chosen expiries.")
    else:
        st.dataframe(
            pe_pivot.style
                .background_gradient(cmap="Reds", axis=None)
                .format("{:,}"),
            use_container_width=True,
            height=min(560, 38 * (len(pe_pivot) + 1)),
        )

st.caption(
    "Darker cell = higher OI at that strike for that expiry. "
    "Spot a vertical band → consistent strike sentiment across expiries. "
    "Spot a horizontal band → that expiry attracts most activity (usually the nearest weekly)."
)


# ───────────────────────── Max-pain history (NSE bhavcopy) ─────────────────────────
import io  # noqa: E402
import zipfile  # noqa: E402
from datetime import date as _date, timedelta  # noqa: E402


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _fetch_bhavcopy(yyyymmdd: str) -> pd.DataFrame | None:
    """Download NSE's daily F&O bhavcopy CSV (returns None on holiday/missing)."""
    url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{yyyymmdd}_F_0000.csv.zip"
    s = cffi.Session(impersonate="chrome120")
    try:
        r = s.get(url, timeout=20)
        if r.status_code != 200 or len(r.content) < 1000:
            return None
        z = zipfile.ZipFile(io.BytesIO(r.content))
        with z.open(z.namelist()[0]) as f:
            return pd.read_csv(f)
    except Exception:
        return None


def _max_pain_from_bhav(bhav: pd.DataFrame, sym: str, exp_iso: str) -> dict | None:
    """Filter bhavcopy → compute max-pain / spot / PCR for one symbol+expiry."""
    rows = bhav[
        (bhav["TckrSymb"] == sym.upper())
        & (bhav["XpryDt"] == exp_iso)
        & (bhav["OptnTp"].isin(["CE", "PE"]))
    ]
    if rows.empty:
        return None
    ce = rows[rows["OptnTp"] == "CE"].groupby("StrkPric")["OpnIntrst"].sum()
    pe = rows[rows["OptnTp"] == "PE"].groupby("StrkPric")["OpnIntrst"].sum()
    all_strikes = sorted(set(ce.index) | set(pe.index))
    ce_arr = np.array([float(ce.get(k, 0)) for k in all_strikes])
    pe_arr = np.array([float(pe.get(k, 0)) for k in all_strikes])
    ks = np.array(all_strikes, dtype=float)
    losses = [
        float((np.clip(k - ks, 0, None) * ce_arr).sum() + (np.clip(ks - k, 0, None) * pe_arr).sum())
        for k in ks
    ]
    mp = int(ks[int(np.argmin(losses))])
    spot = float(rows["UndrlygPric"].iloc[0])
    tot_ce, tot_pe = float(ce_arr.sum()), float(pe_arr.sum())
    return {
        "max_pain": mp, "spot": spot,
        "pcr": tot_pe / tot_ce if tot_ce else 0,
        "tot_ce_oi": int(tot_ce), "tot_pe_oi": int(tot_pe),
    }


st.markdown(section_header("📈", f"Max-pain history · {symbol} · {expiry}"), unsafe_allow_html=True)

n_days = st.slider("Trading days back", 3, 15, 7, key="mp_days")

# Walk back collecting trading days (skip weekends; NSE holidays surface as bhavcopy-missing)
collected = []
d = _date.today() - timedelta(days=1)  # start with yesterday (today's bhavcopy publishes after close)
tried = 0
with st.spinner(f"Fetching last {n_days} bhavcopies from NSE archives…"):
    while len(collected) < n_days and tried < n_days * 3:
        tried += 1
        if d.weekday() < 5:  # Mon-Fri only
            bhav = _fetch_bhavcopy(d.strftime("%Y%m%d"))
            if bhav is not None:
                snap = _max_pain_from_bhav(bhav, symbol, expiry)
                if snap:
                    collected.append({"date": d.isoformat(), **snap})
        d -= timedelta(days=1)

if not collected:
    st.warning(
        "No bhavcopy data found for this expiry in the lookback window. "
        "The chosen expiry may be newer than any closed trading day."
    )
else:
    hist = pd.DataFrame(collected).sort_values("date").reset_index(drop=True)
    hist_chart = hist.set_index("date")[["spot", "max_pain"]]

    h1, h2 = st.columns([3, 2])
    with h1:
        st.markdown("**Spot vs Max Pain** — convergence on expiry day signals option-writer pin")
        st.line_chart(hist_chart, color=["#fafafa", "#8b5cf6"], height=280)
    with h2:
        st.markdown("**Daily snapshot**")
        show = hist[["date", "spot", "max_pain", "pcr"]].copy()
        show["gap"] = (show["spot"] - show["max_pain"]).round(2)
        show["pcr"] = show["pcr"].round(2)
        show["spot"] = show["spot"].round(2)
        st.dataframe(
            show.style.format({"spot": "{:,.2f}", "max_pain": "{:,}", "gap": "{:+,.2f}"}),
            use_container_width=True, hide_index=True,
        )

    # Simple read-out
    today_mp = collected[-1]["max_pain"]
    week_avg_mp = int(np.mean([c["max_pain"] for c in collected]))
    today_gap = collected[-1]["spot"] - today_mp
    pcr_avg = float(np.mean([c["pcr"] for c in collected]))
    pcr_today = collected[-1]["pcr"]
    pcr_delta = pcr_today - pcr_avg

    mp1, mp2, mp3, mp4 = st.columns(4)
    mp1.metric("Latest max pain", f"{today_mp:,}")
    mp2.metric(f"{n_days}-day avg max pain", f"{week_avg_mp:,}", f"{today_mp - week_avg_mp:+,}")
    mp3.metric("Latest spot − max pain", f"{today_gap:+,.2f}")
    mp4.metric("PCR (today vs avg)", f"{pcr_today:.2f}", f"{pcr_delta:+.2f}")

    st.caption(
        "Source: NSE F&O bhavcopy (free public archive) · one CSV per trading day · cached 24h. "
        "Holidays and missing days are skipped automatically."
    )
