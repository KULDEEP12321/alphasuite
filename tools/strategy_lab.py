"""
Strategy Lab: natural-language → JSON DSL → backtest.

DSL schema (a Strategy object):
{
  "name": str,
  "symbol": "BTCUSDT",
  "interval": "1m"|"5m"|"15m"|"30m"|"1h"|"4h"|"1d",
  "entry": {
    "type": "time"|"ma_crossover"|"rsi"|"breakout",
    "params": { ... per type ... }
  },
  "direction_logic": {
    "type": "always_long"|"always_short"|"conditional",
    "condition": { ... only if conditional ... }
  },
  "exits": {
    "stop_loss":   {"unit": "points"|"percent", "value": float},
    "take_profit": {"unit": "points"|"percent", "value": float}
  },
  "sizing": {
    "mode": "fixed_usd"|"compound"|"fixed_risk_pct",
    "value": float            # USD for fixed_usd, % of equity for fixed_risk_pct, ignored for compound
  },
  "capital": float
}
"""
from __future__ import annotations

import json
import os
from typing import Any
import requests
import pandas as pd
from groq import Groq

INTERVAL_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}

ALLOWED_ENTRY_TYPES = {"time", "ma_crossover", "rsi", "breakout"}
ALLOWED_DIRECTION_TYPES = {"always_long", "always_short", "conditional"}
ALLOWED_SIZING_MODES = {"fixed_usd", "compound", "fixed_risk_pct"}
ALLOWED_INTERVALS = set(INTERVAL_MS.keys())

SYSTEM_PROMPT = """You are a trading-strategy parser. The user describes a strategy in natural language. You must output STRICT JSON matching the schema below — no markdown, no commentary, just the JSON object.

Schema:
{
  "name": "<short descriptive name>",
  "symbol": "<one of BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, DOGEUSDT, ADAUSDT>",
  "interval": "<one of 1m, 5m, 15m, 30m, 1h, 4h, 1d>",
  "entry": {
    "type": "<time | ma_crossover | rsi | breakout>",
    "params": { ... }
  },
  "direction_logic": {
    "type": "<always_long | always_short | conditional>",
    "condition": { ... only if conditional ... }
  },
  "exits": {
    "stop_loss":   {"unit": "<points | percent>", "value": <number>},
    "take_profit": {"unit": "<points | percent>", "value": <number>}
  },
  "sizing": {
    "mode": "<fixed_usd | compound | fixed_risk_pct>",
    "value": <number, ignored when mode=compound>
  },
  "capital": <starting capital in USD>
}

Entry param formats by type:
- type=time:        {"entry_time_utc":"HH:MM"}
- type=ma_crossover: {"fast":<int>, "slow":<int>}  # signal fires when fast crosses slow
- type=rsi:         {"period":<int>, "oversold":<float>, "overbought":<float>}
- type=breakout:    {"lookback":<int>}              # N-bar high/low breakout

Direction logic 'conditional' param formats (pick one):
- {"kind":"price_change","from_time_utc":"HH:MM","compare":"above_signal_means_long"}
  → at entry, if current price > price at from_time_utc, go long; else short
- {"kind":"ma_filter","period":<int>,"above_means_long":true}
  → long if close above MA, short if below
- {"kind":"rsi_filter","period":<int>,"long_if_above":<float>}
  → long if RSI > threshold, short if <

Time interpretation:
- "9:30 AM" or "09:30" → "09:30" (UTC if not stated, no DST). "7 PM IST" = "13:30" UTC.
- "points" = absolute USD distance from entry (e.g., 300 points on BTCUSDT = $300).
- "percent" = % of entry price.

If the user is vague, fill sensible defaults:
- interval: 15m
- capital: 1000
- sizing: compound
- symbol: BTCUSDT

ONLY return the JSON. Do not wrap in ```json``` or any prose. Start with { and end with }.
"""


def parse_strategy(text: str, *, model: str | None = None, api_key: str | None = None) -> dict:
    """Send NL → Groq → parsed strategy dict. Raises on bad JSON."""
    api_key = api_key or os.getenv("GROQ_API_KEY")
    model = model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY missing from environment")
    client = Groq(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text.strip()},
        ],
        temperature=0.1,
        max_tokens=900,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content.strip()
    return json.loads(raw)


def validate_strategy(spec: dict) -> list[str]:
    """Returns list of validation errors (empty if ok)."""
    errs = []

    def need(d, k, ctx=""):
        if k not in d:
            errs.append(f"missing '{k}' in {ctx or 'spec'}")
            return False
        return True

    need(spec, "name") and not isinstance(spec["name"], str) and errs.append("name must be string")
    if need(spec, "symbol") and spec["symbol"] not in {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"}:
        errs.append(f"unknown symbol '{spec['symbol']}'")
    if need(spec, "interval") and spec["interval"] not in ALLOWED_INTERVALS:
        errs.append(f"unsupported interval '{spec['interval']}' (use {sorted(ALLOWED_INTERVALS)})")

    if need(spec, "entry"):
        e = spec["entry"]
        if need(e, "type", "entry") and e["type"] not in ALLOWED_ENTRY_TYPES:
            errs.append(f"unknown entry.type '{e['type']}' (allowed: {sorted(ALLOWED_ENTRY_TYPES)})")
        need(e, "params", "entry")

    if need(spec, "direction_logic"):
        d = spec["direction_logic"]
        if need(d, "type", "direction_logic") and d["type"] not in ALLOWED_DIRECTION_TYPES:
            errs.append(f"unknown direction_logic.type '{d['type']}'")
        if d.get("type") == "conditional" and "condition" not in d:
            errs.append("direction_logic.condition required when type=conditional")

    if need(spec, "exits"):
        x = spec["exits"]
        for k in ("stop_loss", "take_profit"):
            if need(x, k, "exits"):
                v = x[k]
                if need(v, "unit", f"exits.{k}") and v["unit"] not in {"points", "percent"}:
                    errs.append(f"exits.{k}.unit must be 'points' or 'percent'")
                need(v, "value", f"exits.{k}")

    if need(spec, "sizing"):
        s = spec["sizing"]
        if need(s, "mode", "sizing") and s["mode"] not in ALLOWED_SIZING_MODES:
            errs.append(f"unknown sizing.mode '{s['mode']}'")

    if "capital" not in spec or not isinstance(spec["capital"], (int, float)):
        errs.append("capital must be a number")

    return errs


# ------------ Data fetching ------------
def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Paginated Binance klines fetcher."""
    out: list[list] = []
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
    df = pd.DataFrame(out, columns=["t", "o", "h", "l", "c", "v", "ct", "qv", "n", "tbb", "tbq", "i"])
    df = df[["t", "o", "h", "l", "c", "v"]].astype({"t": "int64"})
    for col in ["o", "h", "l", "c", "v"]:
        df[col] = df[col].astype(float)
    df["dt"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df["date"] = df["dt"].dt.date
    df["hhmm"] = df["dt"].dt.strftime("%H:%M")
    return df.reset_index(drop=True)


# ------------ Indicators ------------
def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


# ------------ Entry signal detection ------------
def detect_entry_bars(df: pd.DataFrame, entry: dict) -> list[int]:
    """Returns list of df indices where an entry should fire."""
    etype = entry["type"]
    p = entry.get("params", {})

    if etype == "time":
        t = p.get("entry_time_utc", "13:30")
        return df.index[df["hhmm"] == t].tolist()

    if etype == "ma_crossover":
        fast = int(p.get("fast", 9))
        slow = int(p.get("slow", 21))
        f = df["c"].rolling(fast).mean()
        s = df["c"].rolling(slow).mean()
        cross_up = (f.shift(1) <= s.shift(1)) & (f > s)
        cross_dn = (f.shift(1) >= s.shift(1)) & (f < s)
        sig = cross_up | cross_dn
        return df.index[sig.fillna(False)].tolist()

    if etype == "rsi":
        period = int(p.get("period", 14))
        oversold = float(p.get("oversold", 30))
        overbought = float(p.get("overbought", 70))
        rsi = _rsi(df["c"], period)
        sig = ((rsi.shift(1) >= oversold) & (rsi < oversold)) | ((rsi.shift(1) <= overbought) & (rsi > overbought))
        return df.index[sig.fillna(False)].tolist()

    if etype == "breakout":
        lookback = int(p.get("lookback", 20))
        roll_high = df["h"].rolling(lookback).max()
        roll_low = df["l"].rolling(lookback).min()
        broke_up = df["c"] > roll_high.shift(1)
        broke_dn = df["c"] < roll_low.shift(1)
        sig = broke_up | broke_dn
        return df.index[sig.fillna(False)].tolist()

    raise ValueError(f"unknown entry.type {etype}")


def decide_direction(df: pd.DataFrame, ent_idx: int, entry: dict, direction_logic: dict) -> str | None:
    """Return 'long' or 'short' (or None to skip)."""
    dt = direction_logic["type"]
    etype = entry["type"]
    p = entry.get("params", {})

    if dt == "always_long":
        return "long"
    if dt == "always_short":
        return "short"

    # Conditional logic — uses entry-specific or generic info
    # Default fallbacks per entry type:
    if etype == "ma_crossover":
        fast = int(p.get("fast", 9))
        slow = int(p.get("slow", 21))
        f = df["c"].rolling(fast).mean().iloc[ent_idx]
        s = df["c"].rolling(slow).mean().iloc[ent_idx]
        return "long" if f > s else "short"
    if etype == "rsi":
        period = int(p.get("period", 14))
        oversold = float(p.get("oversold", 30))
        rsi = _rsi(df["c"], period).iloc[ent_idx]
        return "long" if rsi < oversold else "short"
    if etype == "breakout":
        lookback = int(p.get("lookback", 20))
        roll_high = df["h"].rolling(lookback).max().iloc[ent_idx - 1] if ent_idx > 0 else df["h"].iloc[ent_idx]
        return "long" if df["c"].iloc[ent_idx] > roll_high else "short"

    # Generic conditionals (used by time-based entries)
    cond = direction_logic.get("condition", {}) or {}
    kind = cond.get("kind")
    if kind == "price_change":
        ft = cond.get("from_time_utc", "09:30")
        same_day = df[(df["date"] == df.iloc[ent_idx]["date"]) & (df["hhmm"] == ft)]
        if same_day.empty:
            return None
        ref = float(same_day.iloc[0]["o"])
        cur = float(df.iloc[ent_idx]["o"])
        return "long" if cur > ref else ("short" if cur < ref else None)
    if kind == "ma_filter":
        period = int(cond.get("period", 50))
        ma = df["c"].rolling(period).mean().iloc[ent_idx]
        cur = df["c"].iloc[ent_idx]
        above_long = bool(cond.get("above_means_long", True))
        is_above = cur > ma
        return "long" if (is_above == above_long) else "short"
    if kind == "rsi_filter":
        period = int(cond.get("period", 14))
        thresh = float(cond.get("long_if_above", 50))
        rsi = _rsi(df["c"], period).iloc[ent_idx]
        return "long" if rsi > thresh else "short"

    return None


# ------------ Backtest ------------
def _sl_tp_prices(direction: str, entry_price: float, sl_cfg: dict, tp_cfg: dict) -> tuple[float, float]:
    def dist(cfg):
        if cfg["unit"] == "points":
            return float(cfg["value"])
        return entry_price * float(cfg["value"]) / 100.0

    sl_d = dist(sl_cfg)
    tp_d = dist(tp_cfg)
    if direction == "long":
        return entry_price - sl_d, entry_price + tp_d
    return entry_price + sl_d, entry_price - tp_d


def run_backtest(spec: dict, df: pd.DataFrame) -> pd.DataFrame:
    sl_cfg = spec["exits"]["stop_loss"]
    tp_cfg = spec["exits"]["take_profit"]
    sizing = spec["sizing"]
    init_cap = float(spec["capital"])
    equity = init_cap
    in_trade_until_idx = -1
    trades = []

    entry_idxs = detect_entry_bars(df, spec["entry"])
    for ent_idx in entry_idxs:
        if ent_idx <= in_trade_until_idx:
            continue  # don't pyramid; wait for current trade to close
        # Need open at entry bar
        if ent_idx >= len(df):
            continue
        ent_row = df.iloc[ent_idx]
        ent_price = float(ent_row["o"])
        direction = decide_direction(df, ent_idx, spec["entry"], spec["direction_logic"])
        if direction is None:
            continue

        sl, tp = _sl_tp_prices(direction, ent_price, sl_cfg, tp_cfg)

        # Walk forward
        exit_price = None
        exit_reason = "OPEN"
        exit_dt = None
        exit_idx = None
        for j in range(ent_idx + 1, len(df)):
            row = df.iloc[j]
            if direction == "long":
                hit_sl = row["l"] <= sl
                hit_tp = row["h"] >= tp
            else:
                hit_sl = row["h"] >= sl
                hit_tp = row["l"] <= tp
            if hit_sl and hit_tp:
                exit_price, exit_reason, exit_dt, exit_idx = sl, "SL", row["dt"], j
                break
            if hit_sl:
                exit_price, exit_reason, exit_dt, exit_idx = sl, "SL", row["dt"], j
                break
            if hit_tp:
                exit_price, exit_reason, exit_dt, exit_idx = tp, "TP", row["dt"], j
                break

        if exit_price is None:
            last = df.iloc[-1]
            exit_price = float(last["c"])
            exit_dt = last["dt"]
            exit_idx = len(df) - 1

        # Sizing
        mode = sizing["mode"]
        if mode == "fixed_usd":
            stake = float(sizing.get("value", 100))
        elif mode == "compound":
            stake = max(equity, 0)
        else:  # fixed_risk_pct
            risk_pct = float(sizing.get("value", 1.0))
            risk_dollar = equity * (risk_pct / 100.0)
            sl_dist = abs(ent_price - sl)
            stake = (risk_dollar / sl_dist) * ent_price if sl_dist > 0 else 0
            stake = min(stake, equity)

        if stake <= 0:
            break

        coins = stake / ent_price
        pnl = coins * (exit_price - ent_price) if direction == "long" else coins * (ent_price - exit_price)
        equity += pnl
        in_trade_until_idx = exit_idx

        trades.append({
            "entry_dt": ent_row["dt"],
            "direction": direction,
            "entry": ent_price,
            "sl": sl, "tp": tp,
            "exit_dt": exit_dt,
            "exit": exit_price,
            "reason": exit_reason,
            "stake_usd": stake,
            "pnl": pnl,
            "equity_after": equity,
        })

    return pd.DataFrame(trades)
