"""
AlphaSuite MCP server — exposes the same data sources our Streamlit pages
use (Binance crypto, yfinance for US/Indian stocks, Sensibull for NSE
option chain) as MCP tools so Claude can fetch live market data during
sessions.

Wired into Claude Code via .mcp.json at the project root. No broker
integration, no order placement — read-only market data.

Run standalone for debugging:
    python -m mcp_server.server
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import requests
import yfinance as yf
from curl_cffi import requests as cffi
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("alphasuite-data")

INDIA_INDEX_ALIAS = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "SENSEX": "^BSESN",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
    "MIDCPNIFTY": "NIFTY_MID_SELECT.NS",
}


def _classify(symbol: str) -> str:
    s = symbol.upper()
    if s.endswith("USDT") or s.endswith("BUSD"):
        return "crypto"
    if (
        s.endswith(".NS") or s.endswith(".BO")
        or s.startswith("^NS") or s.startswith("^BSE")
        or s in INDIA_INDEX_ALIAS
    ):
        return "india"
    return "us"


def _resolve_for_yfinance(symbol: str) -> str:
    """Friendly NSE names → yfinance tickers ('NIFTY' → '^NSEI')."""
    return INDIA_INDEX_ALIAS.get(symbol.upper(), symbol)


# ───────────────────────── Tools ─────────────────────────

@mcp.tool()
def get_quote(symbol: str, market: str = "auto") -> dict:
    """
    Get the current quote for a symbol.

    Args:
        symbol: Crypto 'BTCUSDT'; US 'AAPL'; India 'NIFTY' / 'BANKNIFTY' / 'RELIANCE.NS'.
        market: 'crypto' | 'us' | 'india' | 'auto' (default, sniffed from symbol shape).

    Returns: { last, change_pct, day_high, day_low, volume, market, source, symbol }.
    """
    if market == "auto":
        market = _classify(symbol)

    if market == "crypto":
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/24hr",
            params={"symbol": symbol}, timeout=10,
        )
        r.raise_for_status()
        d = r.json()
        return {
            "symbol": symbol, "market": "crypto",
            "last": float(d["lastPrice"]),
            "change_pct": float(d["priceChangePercent"]),
            "day_high": float(d["highPrice"]),
            "day_low": float(d["lowPrice"]),
            "volume": float(d["volume"]),
            "source": "Binance (real-time)",
        }

    yf_sym = _resolve_for_yfinance(symbol)
    info = yf.Ticker(yf_sym).fast_info
    last = float(info.get("lastPrice") or 0)
    prev = float(info.get("previousClose") or 0)
    return {
        "symbol": symbol, "yf_symbol": yf_sym, "market": market,
        "last": last,
        "change_pct": ((last - prev) / prev * 100) if prev else 0,
        "day_high": float(info.get("dayHigh") or 0),
        "day_low": float(info.get("dayLow") or 0),
        "volume": float(info.get("tenDayAverageVolume") or 0),
        "source": "Yahoo Finance (~15 min delayed)",
    }


@mcp.tool()
def get_chart(
    symbol: str,
    interval: str = "1d",
    lookback_days: int = 90,
    market: str = "auto",
) -> dict:
    """
    Get OHLCV bars for a symbol.

    Args:
        symbol: see get_quote.
        interval: '1m' | '5m' | '15m' | '30m' | '1h' | '4h' (crypto-only) | '1d'.
        lookback_days: how many days back from now (1-2000).
        market: 'crypto' | 'us' | 'india' | 'auto'.

    Returns: { symbol, market, interval, bars: [{time_iso, open, high, low, close, volume}, ...] }.
    """
    if market == "auto":
        market = _classify(symbol)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)

    if market == "crypto":
        interval_ms = {
            "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
            "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
        }
        if interval not in interval_ms:
            raise ValueError(f"crypto interval must be one of {list(interval_ms)}")
        out = []
        cur = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        step = interval_ms[interval]
        while cur < end_ms:
            r = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "startTime": cur, "endTime": end_ms, "limit": 1000},
                timeout=15,
            )
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            out.extend(batch)
            if len(batch) < 1000:
                break
            cur = batch[-1][0] + step
        bars = [
            {
                "time_iso": datetime.fromtimestamp(b[0] / 1000, tz=timezone.utc).isoformat(),
                "open": float(b[1]), "high": float(b[2]), "low": float(b[3]),
                "close": float(b[4]), "volume": float(b[5]),
            }
            for b in out
        ]
        return {"symbol": symbol, "market": "crypto", "interval": interval, "bars": bars, "source": "Binance"}

    # yfinance path (US + India)
    yf_sym = _resolve_for_yfinance(symbol)
    if interval == "1d":
        period = f"{max(lookback_days, 1)}d"
    elif interval == "1m":
        period = "5d"
    elif interval in ("5m", "15m", "30m", "1h"):
        period = "1mo" if lookback_days <= 30 else ("3mo" if lookback_days <= 90 else "6mo")
    elif interval == "4h":
        raise ValueError("4h interval is crypto-only; use 1h or 1d for stocks.")
    else:
        raise ValueError(f"stock interval must be one of 1m/5m/15m/30m/1h/1d, got {interval!r}")

    df = yf.Ticker(yf_sym).history(period=period, interval=interval, auto_adjust=False)
    if df.empty:
        return {"symbol": symbol, "yf_symbol": yf_sym, "market": market, "interval": interval, "bars": [], "source": "Yahoo Finance"}
    bars = [
        {
            "time_iso": ts.isoformat(),
            "open": float(row["Open"]), "high": float(row["High"]), "low": float(row["Low"]),
            "close": float(row["Close"]), "volume": float(row["Volume"]),
        }
        for ts, row in df.iterrows()
    ]
    return {
        "symbol": symbol, "yf_symbol": yf_sym, "market": market,
        "interval": interval, "bars": bars,
        "source": "Yahoo Finance (~15 min delayed)",
    }


@mcp.tool()
def get_option_chain(symbol: str, expiry: str | None = None) -> dict:
    """
    NSE option chain via Sensibull's free public endpoint.

    Args:
        symbol: 'NIFTY' | 'BANKNIFTY' | 'FINNIFTY' | 'MIDCPNIFTY' | NSE equity 'RELIANCE' etc.
        expiry: ISO 'YYYY-MM-DD'. None = nearest expiry.

    Returns: { symbol, expiry, available_expiries, spot, atm_strike, pcr, max_pain,
               total_ce_oi, total_pe_oi, strikes: [{strike, ce: {ltp,vol,oi}, pe: {...}}, ...] }.
    """
    s = cffi.Session(impersonate="chrome120")
    r = s.get(f"https://api.sensibull.com/v1/instruments/{symbol.upper()}", timeout=15)
    r.raise_for_status()
    body = r.json()
    if not body.get("status") or "data" not in body:
        raise RuntimeError(f"Sensibull returned: {str(body)[:200]}")

    instruments = body["data"]
    expiries = sorted({
        it["expiry"] for it in instruments
        if it.get("segment") == "NFO-OPT" and it.get("expiry")
    })
    if not expiries:
        return {"symbol": symbol, "error": "no F&O expiries found"}
    chosen = expiry or expiries[0]
    if chosen not in expiries:
        return {"symbol": symbol, "expiry": chosen,
                "error": f"expiry not found", "available_expiries": expiries[:10]}

    # Spot via yfinance
    yf_sym = _resolve_for_yfinance(symbol if symbol.upper() in INDIA_INDEX_ALIAS else f"{symbol}.NS")
    try:
        spot = float(yf.Ticker(yf_sym).fast_info.get("lastPrice") or 0)
    except Exception:
        spot = 0.0

    by_strike: dict[float, dict] = {}
    for it in instruments:
        if it.get("segment") != "NFO-OPT" or it.get("expiry") != chosen:
            continue
        strike = float(it["strike"])
        side = "ce" if it["instrument_type"] == "CE" else "pe"
        row = by_strike.setdefault(strike, {"strike": strike, "ce": None, "pe": None})
        row[side] = {
            "ltp": float(it.get("last_price") or 0),
            "vol": int(it.get("volume") or 0),
            "oi": int(it.get("oi") or 0),
        }
    strikes = sorted(by_strike.values(), key=lambda x: x["strike"])

    atm = None
    if strikes and spot:
        atm = min(strikes, key=lambda x: abs(x["strike"] - spot))["strike"]
    total_ce_oi = sum((s["ce"]["oi"] if s["ce"] else 0) for s in strikes)
    total_pe_oi = sum((s["pe"]["oi"] if s["pe"] else 0) for s in strikes)
    pcr = total_pe_oi / total_ce_oi if total_ce_oi else 0

    ks = np.array([s["strike"] for s in strikes], dtype=float)
    ce_arr = np.array([(s["ce"]["oi"] if s["ce"] else 0) for s in strikes], dtype=float)
    pe_arr = np.array([(s["pe"]["oi"] if s["pe"] else 0) for s in strikes], dtype=float)
    losses = []
    for k in ks:
        losses.append(float((np.clip(k - ks, 0, None) * ce_arr).sum() + (np.clip(ks - k, 0, None) * pe_arr).sum()))
    max_pain = int(ks[int(np.argmin(losses))]) if losses else None

    return {
        "symbol": symbol, "expiry": chosen,
        "available_expiries": expiries,
        "spot": spot, "atm_strike": atm,
        "pcr": round(pcr, 3), "max_pain": max_pain,
        "total_ce_oi": int(total_ce_oi), "total_pe_oi": int(total_pe_oi),
        "strikes": strikes,
        "source": "Sensibull (chain) + Yahoo Finance (spot)",
    }


@mcp.tool()
def list_supported_symbols(market: str = "all") -> dict:
    """
    List symbols this MCP has been tested against.

    Args:
        market: 'crypto' | 'us' | 'india' | 'india_options_underlyings' | 'all'.
    """
    data = {
        "crypto": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"],
        "us": ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META", "SPY", "QQQ"],
        "india": [
            "NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY",
            "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS",
            "ICICIBANK.NS", "SBIN.NS", "AXISBANK.NS", "KOTAKBANK.NS",
            "ITC.NS", "HINDUNILVR.NS",
        ],
        "india_options_underlyings": [
            "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN",
        ],
    }
    if market == "all":
        return data
    return {market: data.get(market, [])}


if __name__ == "__main__":
    mcp.run()
