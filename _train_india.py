"""Train donchian_breakout (walk-forward, no-tune) on every Indian ticker present in the DB."""
import sys, subprocess, sqlite3

INDICES = [
    "^NSEI","^BSESN","^NSEBANK","^CNXIT","^CNXAUTO","^CNXPHARMA","^CNXFMCG",
    "^CNXMETAL","^CNXENERGY","^CNXREALTY","^CNXINFRA","^CNXPSUBANK","^CNXMEDIA",
    "^CNXPSE","^CNXCMDT","^CNXCONSUM","^CNXSERVICE","^CNXFIN","^CNXMNC",
    "^CNX100","^CNX500",
]
NIFTY50 = [
    "ADANIENT","ADANIPORTS","APOLLOHOSP","ASIANPAINT","AXISBANK","BAJAJ-AUTO",
    "BAJFINANCE","BAJAJFINSV","BEL","BHARTIARTL","BPCL","BRITANNIA","CIPLA",
    "COALINDIA","DRREDDY","EICHERMOT","GRASIM","HCLTECH","HDFCBANK","HDFCLIFE",
    "HEROMOTOCO","HINDALCO","HINDUNILVR","ICICIBANK","INDUSINDBK","INFY","ITC",
    "JSWSTEEL","KOTAKBANK","LT","LTIM","M&M","MARUTI","NESTLEIND","NTPC","ONGC",
    "POWERGRID","RELIANCE","SBILIFE","SBIN","SHRIRAMFIN","SUNPHARMA","TATACONSUM",
    "TMPV","TATASTEEL","TCS","TECHM","TITAN","TRENT","ULTRACEMCO","WIPRO",
    # TATAMOTORS.NS -> TMPV.NS after 2025 demerger; LTIM.NS unavailable on Yahoo.
]
WANT = set(INDICES) | {f"{t}.NS" for t in NIFTY50}

# Only train tickers that actually have price data in the DB.
con = sqlite3.connect("alphasuite.db")
cur = con.cursor()
cur.execute("""
    SELECT c.symbol FROM company c
    JOIN price_history p ON p.company_id = c.id
    GROUP BY c.symbol HAVING COUNT(p.id) > 250
""")
have = {r[0] for r in cur.fetchall()}
con.close()

tickers = sorted(WANT & have)
print(f"Training {len(tickers)} Indian tickers (have data): {tickers}", flush=True)

ok, fail = 0, 0
for i, t in enumerate(tickers, 1):
    print(f"=== [{i}/{len(tickers)}] TRAIN {t} ===", flush=True)
    try:
        r = subprocess.run(
            [".venv/bin/python", "quant_engine.py", "train",
             "--ticker", t, "--strategy-type", "donchian_breakout",
             "--no-tune", "--no-plot"],
            capture_output=True, text=True, timeout=1200,
        )
        if r.returncode == 0:
            print(f"[{i}/{len(tickers)}] OK   {t}", flush=True)
            ok += 1
        else:
            tail = (r.stderr or r.stdout).strip().splitlines()[-3:]
            print(f"[{i}/{len(tickers)}] FAIL {t}  rc={r.returncode} :: {' | '.join(tail)}", flush=True)
            fail += 1
    except subprocess.TimeoutExpired:
        print(f"[{i}/{len(tickers)}] FAIL {t}  (timeout >1200s)", flush=True)
        fail += 1
    except Exception as e:
        print(f"[{i}/{len(tickers)}] FAIL {t}  ({type(e).__name__}: {e})", flush=True)
        fail += 1

print(f"DONE training: {ok} ok, {fail} failed", flush=True)
