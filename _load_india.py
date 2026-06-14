"""One-off loader: download Indian indices + Nifty 50 constituents into AlphaSuite DB."""
import sys
from dotenv import load_dotenv
load_dotenv()
from tools.yfinance_tool import load_ticker_data

INDICES = [
    "^NSEI",        # Nifty 50
    "^BSESN",       # BSE Sensex
    "^NSEBANK",     # Nifty Bank
    "^CNXIT",       # Nifty IT
    "^CNXAUTO",     # Nifty Auto
    "^CNXPHARMA",   # Nifty Pharma
    "^CNXFMCG",     # Nifty FMCG
    "^CNXMETAL",    # Nifty Metal
    "^CNXENERGY",   # Nifty Energy
    "^CNXREALTY",   # Nifty Realty
    "^CNXINFRA",    # Nifty Infrastructure
    "^CNXPSUBANK",  # Nifty PSU Bank
    "^CNXMEDIA",    # Nifty Media
    "^CNXPSE",      # Nifty PSE
    "^CNXCMDT",     # Nifty Commodities
    "^CNXCONSUM",   # Nifty Consumption
    "^CNXSERVICE",  # Nifty Services
    "^CNXFIN",      # Nifty Financial Services
    "^CNXMNC",      # Nifty MNC
    "^CNX100",      # Nifty 100
    "^CNX500",      # Nifty 500
]

NIFTY50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "BPCL", "BRITANNIA", "CIPLA", "COALINDIA", "DRREDDY",
    "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK",
    "INFY", "ITC", "JSWSTEEL", "KOTAKBANK", "LT",
    "LTIM", "M&M", "MARUTI", "NESTLEIND", "NTPC",
    "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN",
    "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", "TMPV", "TATASTEEL",
    "TCS", "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
    # NOTE: TATAMOTORS.NS retired after the 2025 demerger -> TMPV.NS (Passenger
    # Vehicles, full history since 1991) + TMCV.NS (Commercial Vehicles, new).
    # LTIM.NS (LTIMindtree) has no Yahoo Finance data available as of 2026-06.
]

group = sys.argv[1] if len(sys.argv) > 1 else "all"
tickers = []
if group in ("all", "indices"):
    tickers += INDICES
if group in ("all", "stocks"):
    tickers += [t if t.endswith(".NS") else f"{t}.NS" for t in NIFTY50]

ok, fail = 0, 0
for i, t in enumerate(tickers, 1):
    try:
        res = load_ticker_data(t, refresh=True)
        if res and res.get("shareprices") is not None and not res["shareprices"].empty:
            n = len(res["shareprices"])
            print(f"[{i}/{len(tickers)}] OK   {t}  ({n} bars)", flush=True)
            ok += 1
        else:
            print(f"[{i}/{len(tickers)}] FAIL {t}  (no data returned)", flush=True)
            fail += 1
    except Exception as e:
        print(f"[{i}/{len(tickers)}] FAIL {t}  ({type(e).__name__}: {e})", flush=True)
        fail += 1

print(f"DONE downloads: {ok} ok, {fail} failed", flush=True)
