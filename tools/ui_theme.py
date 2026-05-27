"""
Shared Modern-Fintech UI theme for the chart-driven pages.

Usage:
    from tools.ui_theme import apply_theme, hero_header, result_panel, chart_options, area_series, section_header
    apply_theme()
    hero_header("🧠 Strategy Lab", chips=[...], subtitle="...")
    ...
    st.markdown(result_panel(final_eq, init_cap, total_pnl, pnl_pct, meta="..."), unsafe_allow_html=True)
    ...
    renderLightweightCharts([{"chart": chart_options(), "series": [area_series(data, accent="#10d9a0")]}], key=...)
"""
from __future__ import annotations

import streamlit as st


# ──────────────────────────── Color tokens ────────────────────────────
ACCENT_1 = "#8b5cf6"   # violet
ACCENT_2 = "#ec4899"   # pink
ACCENT_3 = "#06b6d4"   # cyan
POS = "#10d9a0"        # positive (mint)
NEG = "#ff5470"        # negative (rose)
POS_RGBA = "16,217,160"
NEG_RGBA = "255,84,112"


def apply_theme() -> None:
    """Inject the global Modern-Fintech CSS once per page. Idempotent."""
    st.markdown(_CSS, unsafe_allow_html=True)


def hero_header(title: str, subtitle: str = "", chips: list[str] | None = None) -> None:
    """Render the top-of-page gradient hero with chips and subtitle."""
    chips_html = ""
    if chips:
        parts = []
        for i, c in enumerate(chips):
            dot = '<span class="chip-dot"></span>' if i == 0 else ""
            parts.append(f'<span class="chip">{dot}{c}</span>')
        chips_html = '<p>' + "".join(parts) + '</p>'
    sub_html = f'<p style="margin-top: 0.6rem;">{subtitle}</p>' if subtitle else ""
    st.markdown(
        f"""
        <div class="lab-hero">
            <h1>{title}</h1>
            {chips_html}
            {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_header(num: str | int, label: str) -> str:
    """Returns HTML for a numbered section header. Use with st.markdown(..., unsafe_allow_html=True)."""
    return (
        f'<div class="section-h">'
        f'<span class="num">{num}</span>{label}<span class="bar"></span>'
        f'</div>'
    )


def result_panel(
    final_eq: float,
    init_cap: float,
    total_pnl: float,
    pnl_pct: float,
    meta: str = "",
    pnl_label: str = "Net P&L",
) -> str:
    """The big glowing centerpiece result card. Returns HTML; pass to st.markdown."""
    is_win = total_pnl >= 0
    accent = POS if is_win else NEG
    glow = POS_RGBA if is_win else NEG_RGBA
    sign = "+" if total_pnl >= 0 else ""
    arrow = "▲" if is_win else "▼"
    return f"""
    <div style="
        position: relative;
        background:
            radial-gradient(ellipse 60% 80% at 0% 50%, rgba({glow},0.18), transparent 70%),
            radial-gradient(ellipse 50% 70% at 100% 50%, rgba(139,92,246,0.14), transparent 70%),
            rgba(255,255,255,0.025);
        border: 1px solid rgba({glow},0.35);
        border-radius: 22px;
        padding: 2.2rem 2.6rem;
        margin-bottom: 1.4rem;
        backdrop-filter: blur(24px) saturate(200%);
        -webkit-backdrop-filter: blur(24px) saturate(200%);
        box-shadow: 0 20px 60px rgba(0,0,0,0.4), 0 0 80px rgba({glow},0.12);
        overflow: hidden;
    ">
        <div style="position: absolute; top: -40px; right: -40px; width: 200px; height: 200px;
                    background: radial-gradient(circle, rgba({glow},0.25), transparent 70%);
                    filter: blur(40px); pointer-events: none;"></div>
        <div style="display: flex; justify-content: space-between; align-items: flex-end; gap: 2rem; position: relative;">
            <div>
                <div style="font-size: 0.7rem; color: #71717a; letter-spacing: 0.16em; text-transform: uppercase; font-weight: 700; margin-bottom: 0.5rem;">
                    ✦ Final equity
                </div>
                <div style="font-size: 4.2rem; font-weight: 800; line-height: 0.95; letter-spacing: -0.03em;
                            background: linear-gradient(120deg, #fff 0%, {accent} 100%);
                            -webkit-background-clip: text; background-clip: text; color: transparent;
                            font-feature-settings: 'tnum' 1;">
                    ${final_eq:,.2f}
                </div>
                <div style="margin-top: 0.8rem; color: #a1a1aa; font-size: 0.92rem; font-weight: 500;">
                    {meta} started <span style="color: #fafafa; font-weight: 600;">${init_cap:,.2f}</span>
                </div>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 0.7rem; color: #71717a; letter-spacing: 0.16em; text-transform: uppercase; font-weight: 700; margin-bottom: 0.5rem;">
                    {pnl_label}
                </div>
                <div style="font-size: 2.6rem; font-weight: 800; color: {accent}; line-height: 0.95; letter-spacing: -0.02em; font-feature-settings: 'tnum' 1;">
                    {sign}${total_pnl:,.2f}
                </div>
                <div style="margin-top: 0.6rem; font-size: 1.15rem; color: {accent}; font-weight: 700;
                            display: inline-flex; align-items: center; gap: 0.4rem;
                            background: rgba({glow},0.12); padding: 0.3rem 0.7rem;
                            border-radius: 999px; border: 1px solid rgba({glow},0.3);">
                    {arrow} {sign}{pnl_pct:.2f}%
                </div>
            </div>
        </div>
    </div>
    """


def chart_options(height: int = 420) -> dict:
    """Lightweight-charts options shaped to the Modern-Fintech palette (transparent bg, soft grid)."""
    return {
        "height": height,
        "layout": {
            "background": {"type": "solid", "color": "rgba(0,0,0,0)"},
            "textColor": "#a1a1aa",
            "fontFamily": "Inter, system-ui, sans-serif",
        },
        "grid": {
            "vertLines": {"color": "rgba(255,255,255,0.04)"},
            "horzLines": {"color": "rgba(255,255,255,0.04)"},
        },
        "timeScale": {
            "timeVisible": True,
            "secondsVisible": False,
            "borderColor": "rgba(255,255,255,0.08)",
        },
        "rightPriceScale": {"borderColor": "rgba(255,255,255,0.08)"},
        "crosshair": {"mode": 1},
    }


def area_series(data: list[dict], accent: str = POS, glow_rgba: str | None = None, line_width: int = 3) -> dict:
    """Glowing-area series spec. `data` is a list of {time, value} dicts."""
    if glow_rgba is None:
        glow_rgba = POS_RGBA if accent == POS else (NEG_RGBA if accent == NEG else "139,92,246")
    return {
        "type": "Area",
        "data": data,
        "options": {
            "topColor": f"rgba({glow_rgba}, 0.5)",
            "bottomColor": f"rgba({glow_rgba}, 0.02)",
            "lineColor": accent,
            "lineWidth": line_width,
            "priceLineVisible": False,
            "crosshairMarkerRadius": 6,
            "crosshairMarkerBorderColor": accent,
            "crosshairMarkerBackgroundColor": "#0a0a0f",
        },
    }


def chart_shell_open() -> str:
    """Open tag for a frosted chart container. Pair with chart_shell_close()."""
    return '<div class="chart-shell">'


def chart_shell_close() -> str:
    return '</div>'


# ──────────────────────────── CSS payload ────────────────────────────
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500&display=swap');

:root {
    --accent-1: #8b5cf6;
    --accent-2: #ec4899;
    --accent-3: #06b6d4;
    --pos: #10d9a0;
    --neg: #ff5470;
    --text-1: #fafafa;
    --text-2: #a1a1aa;
    --text-3: #71717a;
    --glass-bg: rgba(255,255,255,0.025);
    --glass-border: rgba(255,255,255,0.08);
    --glass-border-strong: rgba(255,255,255,0.14);
}

html, body, [class*="css"], .stApp, .stMarkdown, p, h1, h2, h3, h4, span, div, label, button {
    font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
    -webkit-font-smoothing: antialiased;
}

[data-testid="stAppViewContainer"] {
    background:
        radial-gradient(ellipse 80% 50% at 20% 0%, rgba(139,92,246,0.18), transparent 60%),
        radial-gradient(ellipse 70% 40% at 80% 100%, rgba(236,72,153,0.12), transparent 60%),
        radial-gradient(ellipse 60% 60% at 50% 50%, rgba(6,182,212,0.05), transparent 70%),
        #07070c;
}

[data-testid="stHeader"] { background: transparent; }
section[data-testid="stSidebar"] {
    background: rgba(10,10,15,0.6);
    backdrop-filter: blur(16px);
    border-right: 1px solid var(--glass-border);
}

.block-container { padding-top: 1.2rem; max-width: 1300px; }

/* ─── Page hero ─── */
.lab-hero {
    position: relative;
    padding: 1.8rem 2rem 1.6rem 2rem;
    border-radius: 20px;
    margin-bottom: 1.5rem;
    background: linear-gradient(135deg, rgba(139,92,246,0.10), rgba(236,72,153,0.08) 60%, rgba(6,182,212,0.05));
    border: 1px solid var(--glass-border-strong);
    backdrop-filter: blur(20px) saturate(180%);
    -webkit-backdrop-filter: blur(20px) saturate(180%);
    overflow: hidden;
}
.lab-hero::before {
    content: "";
    position: absolute; inset: 0;
    background: radial-gradient(circle at 15% 0%, rgba(139,92,246,0.45), transparent 50%);
    opacity: 0.35;
    pointer-events: none;
}
.lab-hero h1 {
    margin: 0;
    font-size: 2rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    background: linear-gradient(120deg, #fff 0%, #d4d4d8 60%, #a1a1aa 100%);
    -webkit-background-clip: text; background-clip: text; color: transparent;
}
.lab-hero p {
    margin: 0.45rem 0 0 0;
    color: var(--text-2);
    font-size: 0.92rem; font-weight: 500;
    position: relative;
}
.lab-hero .chip {
    display: inline-flex; align-items: center; gap: 0.35rem;
    padding: 0.2rem 0.6rem; margin-right: 0.4rem;
    border-radius: 999px;
    font-size: 0.7rem; font-weight: 600;
    background: rgba(255,255,255,0.06);
    border: 1px solid var(--glass-border);
    color: var(--text-1);
}
.lab-hero .chip-dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--pos);
    box-shadow: 0 0 8px var(--pos);
    animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse { 0%,100% {opacity:1;} 50% {opacity:.4;} }

/* ─── Section headers ─── */
.section-h {
    display: flex; align-items: center; gap: 0.5rem;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.16em;
    color: var(--text-3);
    margin: 1.4rem 0 0.7rem 0;
    font-weight: 700;
}
.section-h .num {
    display: inline-flex; align-items: center; justify-content: center;
    width: 22px; height: 22px;
    border-radius: 7px;
    background: linear-gradient(135deg, var(--accent-1), var(--accent-2));
    color: white;
    font-size: 0.72rem; font-weight: 800;
    box-shadow: 0 4px 12px rgba(139,92,246,0.4);
}
.section-h .bar {
    flex: 1; height: 1px;
    background: linear-gradient(90deg, var(--glass-border), transparent);
}

/* ─── Glass cards ─── */
.glass {
    background: var(--glass-bg);
    border: 1px solid var(--glass-border);
    border-radius: 16px;
    padding: 1.2rem 1.4rem;
    backdrop-filter: blur(20px) saturate(180%);
    -webkit-backdrop-filter: blur(20px) saturate(180%);
}

/* ─── Form inputs ─── */
.stTextArea textarea, .stTextInput input, .stNumberInput input, .stDateInput input {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid var(--glass-border) !important;
    border-radius: 10px !important;
    color: var(--text-1) !important;
    font-family: 'JetBrains Mono', ui-monospace, monospace !important;
    font-size: 0.85rem !important;
}
.stTextArea textarea:focus, .stTextInput input:focus, .stNumberInput input:focus {
    border-color: var(--accent-1) !important;
    box-shadow: 0 0 0 3px rgba(139,92,246,0.15) !important;
}
.stSelectbox > div > div {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid var(--glass-border) !important;
    border-radius: 10px !important;
}

/* ─── Buttons ─── */
.stButton button[kind="primary"] {
    background: linear-gradient(135deg, var(--accent-1), var(--accent-2)) !important;
    border: none !important;
    color: white !important;
    font-weight: 600 !important;
    letter-spacing: 0.01em;
    padding: 0.65rem 1.2rem !important;
    border-radius: 12px !important;
    box-shadow: 0 4px 20px rgba(139,92,246,0.35), inset 0 1px 0 rgba(255,255,255,0.2) !important;
    transition: transform 0.15s ease, box-shadow 0.15s ease !important;
}
.stButton button[kind="primary"]:hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 24px rgba(139,92,246,0.5), inset 0 1px 0 rgba(255,255,255,0.25) !important;
}
.stButton button[kind="secondary"] {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid var(--glass-border) !important;
    color: var(--text-1) !important;
    border-radius: 10px !important;
}

/* ─── Metrics ─── */
[data-testid="stMetric"] {
    background: rgba(255,255,255,0.025);
    border: 1px solid var(--glass-border);
    padding: 1rem 1.1rem;
    border-radius: 14px;
    backdrop-filter: blur(20px) saturate(180%);
    -webkit-backdrop-filter: blur(20px) saturate(180%);
    position: relative; overflow: hidden;
    transition: all 0.2s ease;
}
[data-testid="stMetric"]::before {
    content: ""; position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, var(--accent-1), var(--accent-2));
    opacity: 0.7;
}
[data-testid="stMetric"]:hover {
    border-color: var(--glass-border-strong);
    transform: translateY(-1px);
}
[data-testid="stMetricValue"] {
    font-size: 1.5rem !important;
    font-weight: 700 !important;
    color: var(--text-1) !important;
    font-feature-settings: "tnum" 1;
}
[data-testid="stMetricLabel"] {
    font-size: 0.68rem !important;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--text-3) !important;
    font-weight: 600;
}
[data-testid="stMetricDelta"] { font-size: 0.78rem !important; }

/* ─── Dataframe ─── */
[data-testid="stDataFrame"] {
    background: var(--glass-bg);
    border: 1px solid var(--glass-border);
    border-radius: 14px;
    padding: 0.4rem;
    backdrop-filter: blur(20px);
}

/* ─── Alerts ─── */
[data-testid="stAlert"] {
    border-radius: 12px;
    border: 1px solid var(--glass-border) !important;
    backdrop-filter: blur(12px);
}

/* ─── Chart wrapper ─── */
.chart-shell {
    background: rgba(0,0,0,0.25);
    border: 1px solid var(--glass-border);
    border-radius: 18px;
    padding: 0.6rem;
    box-shadow: 0 20px 50px rgba(0,0,0,0.35), inset 0 0 60px rgba(139,92,246,0.04);
    margin-bottom: 0.5rem;
}
iframe[title="streamlit_lightweight_charts.lightweight_charts"] {
    border-radius: 14px;
}
</style>
"""
