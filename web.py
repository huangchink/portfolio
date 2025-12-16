# -*- coding: utf-8 -*-
"""
Portfolio dashboard that can run locally via Flask or export a static HTML file
for GitHub Pages. Usage:

  # 本地啟動伺服器 (http://127.0.0.1:5000)
  python web.py --serve

  # 產出靜態頁面 (預設 docs/index.html，直接推上 GitHub Pages)
  python web.py --output docs/index.html

可同時 --output 與 --serve：產出靜態檔後啟動伺服器方便預覽。
"""

from __future__ import annotations

import argparse
import logging
import os
import threading
import time
from datetime import datetime
from typing import Callable, Dict, List

import pandas as pd
import yfinance as yf
from flask import Flask, request
from pytz import timezone
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
# Trust proxy headers when running behind reverse proxies (e.g. Render)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Silence noisy yfinance messages like "possibly delisted"
logging.getLogger("yfinance").setLevel(logging.ERROR)

# ============== Portfolio Settings ==============
EXCLUDED_ETFS_US = {"VOO", "VEA", "EWT", "XLU", "AVDV", "IDMO"}

US_GROUP_POWER = {"AEP", "DUK", "LEU", "CEG", "HUBB", "ETN", "VST", "XLU"}
US_GROUP_INDEX = {"VOO", "VEA", "EWT"}
US_GROUP_DEFENSE = {"UNH", "KO", "MCD", "COST", "GIS", "YUM"}

US_PORTFOLIO = [
    {"symbol": "VOO", "shares": 70.00, "cost": 506.75},
    {"symbol": "VEA", "shares": 86.80, "cost": 53.55},
    {"symbol": "XLU", "shares": 250, "cost": 42.854},
    {"symbol": "EWT", "shares": 100, "cost": 61.27},
    {"symbol": "PYPL", "shares": 35, "cost": 68.855},
    {"symbol": "TSM", "shares": 32, "cost": 284.1712},
    {"symbol": "SNPS", "shares": 4, "cost": 397.15},
    {"symbol": "YUM", "shares": 1, "cost": 141.34},
    {"symbol": "UNH", "shares": 22, "cost": 310.86},
    {"symbol": "GOOGL", "shares": 73.80, "cost": 176.454},
    {"symbol": "NVDA", "shares": 40.1387, "cost": 133.039},
    {"symbol": "MSTR", "shares": 10, "cost": 287.304},
    {"symbol": "QCOM", "shares": 12, "cost": 161.4525},
    {"symbol": "KO", "shares": 67.47, "cost": 67.96},
    {"symbol": "AEP", "shares": 15, "cost": 105.216},
    {"symbol": "DUK", "shares": 16, "cost": 115.79375},
    {"symbol": "MCD", "shares": 10, "cost": 303.413},
    {"symbol": "CEG", "shares": 7, "cost": 341.88},
    {"symbol": "LEU", "shares": 11, "cost": 293.236},
    {"symbol": "AMZN", "shares": 17, "cost": 221.631176},
    {"symbol": "ETN", "shares": 1, "cost": 365.12},
    {"symbol": "HUBB", "shares": 4, "cost": 413.425},
    {"symbol": "META", "shares": 12, "cost": 713.02},
    {"symbol": "VST", "shares": 4, "cost": 204.68},
    {"symbol": "BABA", "shares": 2, "cost": 169.42},
    {"symbol": "EOSE", "shares": 11, "cost": 13.331},
    {"symbol": "FCX", "shares": 3, "cost": 41.6133},
    {"symbol": "SMR", "shares": 10, "cost": 19.55},
    {"symbol": "GIS", "shares": 2, "cost": 49.695},
    {"symbol": "INTC", "shares": 19, "cost": 37.003},
    {"symbol": "UUUU", "shares": 30, "cost": 16.96},
    {"symbol": "TSLA", "shares": 1.473, "cost": 423.885},
    {"symbol": "VWO", "shares": 60, "cost": 54.74},
]

TW_PORTFOLIO = [
    {"symbol": "0050.TW", "shares": 12507, "cost": 44.56},
    {"symbol": "006208.TW", "shares": 10000, "cost": 115.46},
    {"symbol": "00713.TW", "shares": 10427, "cost": 54.40},
]

GOLD_PORTFOLIO = [
    {"symbol": "GLD", "shares": 16.55, "cost": 300.10},
]

SHORT_TERM_BONDS = [
    {"symbol": "SGOV", "shares": 900, "cost": 100.402495},
    {"symbol": "BOXX", "shares": 100, "cost": 110.71},
]

LONG_TERM_BONDS = [
    {"symbol": "TLT", "shares": 193, "cost": 91.815},
    {"symbol": "IEF", "shares": 80, "cost": 96.81275},
]

CASH_HOLDINGS = [
    {"currency": "TWD", "amount": 400000},
    {"currency": "AUD", "amount": 6851.54},
    {"currency": "JPY", "amount": 417356},
    {"currency": "USD", "amount": 6314},
]

CRYPTO_PORTFOLIO = [
    {"symbol": "BTC", "amount": 0.02994364, "cost": 110046.57},
]

# ============== Simple TTL Cache ==============
_TTL_FAST = 60       # 1 minute
_TTL_NORMAL = 300    # 5 minutes
_TTL_LONG = 3600     # 1 hour

_cache: Dict = {}
_cache_lock = threading.Lock()


def _now() -> float:
    return time.time()


def _get_cache(key):
    with _cache_lock:
        return _cache.get(key)


def _set_cache(key, value):
    with _cache_lock:
        _cache[key] = value


def cached_history(symbol, *, period=None, start=None, end=None, ttl=_TTL_NORMAL):
    key = ("history", symbol, period, start, end)
    entry = _get_cache(key)
    now = _now()
    if entry and (now - entry["ts"] < ttl) and entry["data"] is not None:
        return entry["data"]
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period) if period else ticker.history(start=start, end=end)
        _set_cache(key, {"ts": now, "data": df})
        return df
    except Exception:
        if entry and entry["data"] is not None:
            return entry["data"]
        return pd.DataFrame()


def cached_close(symbol, ttl=_TTL_FAST):
    # Try short period first, then fall back to a longer history.
    for period, t in (("7d", ttl), ("1mo", max(ttl, _TTL_NORMAL))):
        df = cached_history(symbol, period=period, ttl=t)
        if not df.empty and "Close" in df:
            close = df["Close"].dropna()
            if not close.empty:
                return float(close.iloc[-1])
    return "N/A"


def get_tw_stock_price(symbol):
    base = symbol.replace(".TW", "")
    candidates = [f"{base}.TW", f"{base}.TWO", base, f"{base}.TPE"]
    seen = set()
    for sym in candidates:
        if sym in seen:
            continue
        seen.add(sym)
        price = cached_close(sym, ttl=_TTL_FAST)
        if price != "N/A":
            return price
    return "N/A"


def get_crypto_price(symbol):
    return cached_close(f"{symbol}-USD", ttl=_TTL_FAST)


def get_currency_rate(pair, default=1.0):
    for suffix in ["=X", ""]:
        price = cached_close(f"{pair}{suffix}", ttl=_TTL_LONG)
        if price != "N/A":
            return price
    return default


TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Ching's Portfolio</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js"></script>
    <style>
        body { font-family: "Noto Sans TC", "Microsoft JhengHei", Arial, sans-serif; background: #f4f6f8; color: #333; }
        .container { max-width: 1200px; margin: 32px auto; background: #fff; padding: 28px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,.06); }
        h1, h2, h3 { margin: 0 0 8px; color: #2c3e50; }
        h2 { margin-top: 28px; border-bottom: 2px solid #eaecef; padding-bottom: 8px;}
        .meta { color: #6c757d; margin-bottom: 8px; }
        .bar { display:flex; justify-content: space-between; align-items:center; margin: 10px 0 18px; gap: 8px; flex-wrap: wrap; }
        .pill { background:#e3f2fd; color:#1976d2; padding:8px 12px; border-radius:999px; font-weight:600; }
        .summary { background:#f8f9fa; padding:18px; border-radius:10px; margin:18px 0; }
        .summary-row { display:flex; justify-content:space-between; margin:6px 0; font-size: 1.05em; }
        .chart-container { max-width: 450px; margin: 24px auto; }
        table { width:100%; border-collapse: collapse; margin-top: 14px; }
        th, td { border: 1px solid #eaecef; padding: 10px 12px; text-align: left; }
        th { background: #f0f3f6; font-weight: 600; }
        .right { text-align:right; }
        .gain { color:#c62828; font-weight:700; }
        .loss { color:#2e7d32; font-weight:700; }
        .nav { margin-bottom: 8px; }
        .nav a { margin-right: 14px; text-decoration:none; color:#1976d2; font-weight: 500;}
        .badge { display:inline-block; padding:2px 6px; background:#eef2f7; border-radius:6px; font-size: 12px; margin-left: 6px;}
        .muted { color:#6c757d; }
    </style>
</head>
<body>
<div class="container">
    <div class="nav">
        <a href="/">資產總覽</a>
    </div>

    <h1>Ching's Portfolio</h1>
    <div class="meta">更新時間：{{ updated_at }}</div>
    <div class="meta">美元兌台幣：<b>{{ '%.3f' % exchange_rate }}</b></div>

    <div class="summary">
        <div class="summary-row">
            <span>總市值 (TWD)</span>
            <span class="right"><b>{{ '%.0f' % grand_total_market_value_twd }}</b></span>
        </div>
        <div class="summary-row">
            <span>總成本 (TWD)</span>
            <span class="right"><b>{{ '%.0f' % grand_total_cost_twd }}</b></span>
        </div>
        <div class="summary-row">
            <span>總報酬 (TWD)</span>
            <span class="right {% if grand_total_profit_twd > 0 %}gain{% elif grand_total_profit_twd < 0 %}loss{% endif %}">
                <b>{{ '%.0f' % grand_total_profit_twd }}</b> ({{ '%.2f' % grand_total_profit_pct }}%)
            </span>
        </div>
    </div>
    
    <div class="chart-container">
        <canvas id="assetAllocationChart"></canvas>
    </div>

    <div class="chart-container">
        <canvas id="usGroupChart"></canvas>
    </div>

    <h2>美股組合 (USD)</h2>
     <div class="bar">
        <div class="muted">ETF: {{ excluded_join }}</div>
        <label>
            <input type="checkbox" id="toggleEtf" {% if initial_hide_etf %}checked{% endif %}>
            隱藏 ETF
        </label>
    </div>
    <table id="usTable">
        <tr>
            <th>代號</th><th class="right">現價</th><th class="right">成本</th><th class="right">持股數</th><th class="right">市值</th><th class="right">佔比</th><th class="right">個別報酬</th>
        </tr>
        {% for it in us_table %}
        <tr data-us-row data-etf="{{ 1 if it.is_excluded else 0 }}" data-weight-all="{{ it.weight_all_pct_str }}" data-weight-core="{{ it.weight_core_pct_str }}">
            <td>{{ it.symbol }}{% if it.is_excluded %}<span class="badge">ETF</span>{% endif %}</td>
            <td class="right">{{ it.price_str }}</td>
            <td class="right">{{ it.cost_str }}</td>
            <td class="right">{{ it.shares_str }}</td>
            <td class="right">{{ it.mv_str }}</td>
            <td class="right weight-cell">{{ it.weight_display }}</td>
            <td class="right {% if it.profit_pct > 0 %}gain{% elif it.profit_pct < 0 %}loss{% endif %}">{{ it.profit_pct_str }}</td>
        </tr>
        {% endfor %}
    </table>

    <div class="summary">
        <h3>美股總計</h3>
        <div class="summary-row">
            <span>總市值</span><span class="right"><b id="usTotalMVUSD">{{ us_total_market_value_usd_str }}</b> USD (<span id="usTotalMVTWD">{{ us_total_market_value_twd_str }}</span> TWD)</span>
        </div>
        <div class="summary-row">
            <span>總成本</span><span class="right"><b id="usTotalCostUSD">{{ us_total_cost_usd_str }}</b> USD (<span id="usTotalCostTWD">{{ us_total_cost_twd_str }}</span> TWD)</span>
        </div>
        <div class="summary-row">
            <span>總報酬</span>
            <span class="right" id="usProfitWrap">
                <b id="usTotalProfitUSD">{{ us_total_profit_usd_str }}</b> USD
                (<span id="usTotalProfitTWD">{{ us_total_profit_twd_str }}</span> TWD,
                <span id="usTotalProfitPct">{{ us_total_profit_pct_str }}</span>)
            </span>
        </div>
        <div class="muted">核心（排除 ETF）市值：{{ us_core_total_market_value_usd_str }} USD</div>
    </div>

    <h2>台股組合 (TWD)</h2>
    <table>
        <tr>
            <th>代號</th><th class="right">現價</th><th class="right">成本</th><th class="right">持股數</th><th class="right">市值</th><th class="right">佔比</th><th class="right">個別報酬</th>
        </tr>
        {% for it in tw_table %}
        <tr>
            <td>{{ it.symbol }}</td><td class="right">{{ it.price_str }}</td><td class="right">{{ it.cost_str }}</td><td class="right">{{ it.shares_str }}</td><td class="right">{{ it.mv_str }}</td><td class="right">{{ it.weight_str }}</td><td class="right {% if it.profit_pct > 0 %}gain{% elif it.profit_pct < 0 %}loss{% endif %}">{{ it.profit_pct_str }}</td>
        </tr>
        {% endfor %}
    </table>
    <div class="summary">
        <div class="summary-row">
            <span>台股總市值</span><span class="right"><b>{{ '%.0f' % tw_total_market_value }}</b> TWD</span>
        </div>
        <div class="summary-row">
            <span>台股總成本</span><span class="right"><b>{{ '%.0f' % tw_total_cost }}</b> TWD</span>
        </div>
        <div class="summary-row">
            <span>台股總報酬</span>
            <span class="right {% if tw_total_profit_pct > 0 %}gain{% elif tw_total_profit_pct < 0 %}loss{% endif %}">
                <b>{{ '%.0f' % tw_total_profit }}</b> TWD ({{ '%.2f' % tw_total_profit_pct }}%)
            </span>
        </div>
    </div>

    <h2>黃金 (Gold)</h2>
    <table>
        <tr>
            <th>代號</th><th class="right">現價 (USD)</th><th class="right">成本 (USD)</th><th class="right">持有數量</th><th class="right">市值 (USD)</th><th class="right">個別報酬</th>
        </tr>
        {% for it in gold_table %}
        <tr>
            <td>{{ it.symbol }}</td><td class="right">{{ it.price_str }}</td><td class="right">{{ it.cost_str }}</td><td class="right">{{ it.shares_str }}</td><td class="right">{{ it.mv_str }}</td><td class="right {% if it.profit_pct > 0 %}gain{% elif it.profit_pct < 0 %}loss{% endif %}">{{ it.profit_pct_str }}</td>
        </tr>
        {% endfor %}
    </table>
    <div class="summary">
        <div class="summary-row">
            <span>黃金總市值</span><span class="right"><b>{{ '%.2f' % gold_total_market_value_usd }}</b> USD ({{ '%.0f' % (gold_total_market_value_usd * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>黃金總成本</span><span class="right"><b>{{ '%.2f' % gold_total_cost_usd }}</b> USD ({{ '%.0f' % (gold_total_cost_usd * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>黃金總報酬</span>
            <span class="right {% if gold_total_profit_pct > 0 %}gain{% elif gold_total_profit_pct < 0 %}loss{% endif %}">
                <b>{{ '%.2f' % gold_total_profit_usd }}</b> USD ({{ '%.0f' % (gold_total_profit_usd * exchange_rate) }} TWD, {{ '%.2f' % gold_total_profit_pct }}%)
            </span>
        </div>
    </div>

    <h2>短債 (Short-term Bonds)</h2>
    <table>
        <tr>
            <th>代號</th><th class="right">現價 (USD)</th><th class="right">成本 (USD)</th><th class="right">持有數量</th><th class="right">市值 (USD)</th><th class="right">個別報酬</th>
        </tr>
        {% for it in short_term_bonds_table %}
        <tr>
            <td>{{ it.symbol }}</td><td class="right">{{ it.price_str }}</td><td class="right">{{ it.cost_str }}</td><td class="right">{{ it.shares_str }}</td><td class="right">{{ it.mv_str }}</td><td class="right {% if it.profit_pct > 0 %}gain{% elif it.profit_pct < 0 %}loss{% endif %}">{{ it.profit_pct_str }}</td>
        </tr>
        {% endfor %}
    </table>
    <div class="summary">
        <div class="summary-row">
            <span>短債總市值</span><span class="right"><b>{{ '%.2f' % short_term_bonds_total_market_value_usd }}</b> USD ({{ '%.0f' % (short_term_bonds_total_market_value_usd * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>短債總成本</span><span class="right"><b>{{ '%.2f' % short_term_bonds_total_cost_usd }}</b> USD ({{ '%.0f' % (short_term_bonds_total_cost_usd * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>短債總報酬</span>
            <span class="right {% if short_term_bonds_total_profit_pct > 0 %}gain{% elif short_term_bonds_total_profit_pct < 0 %}loss{% endif %}">
                <b>{{ '%.2f' % short_term_bonds_total_profit_usd }}</b> USD ({{ '%.0f' % (short_term_bonds_total_profit_usd * exchange_rate) }} TWD, {{ '%.2f' % short_term_bonds_total_profit_pct }}%)
            </span>
        </div>
    </div>

    <h2>長債 (Long-term Bonds)</h2>
    <table>
        <tr>
            <th>代號</th><th class="right">現價 (USD)</th><th class="right">成本 (USD)</th><th class="right">持有數量</th><th class="right">市值 (USD)</th><th class="right">個別報酬</th>
        </tr>
        {% for it in long_term_bonds_table %}
        <tr>
            <td>{{ it.symbol }}</td><td class="right">{{ it.price_str }}</td><td class="right">{{ it.cost_str }}</td><td class="right">{{ it.shares_str }}</td><td class="right">{{ it.mv_str }}</td><td class="right {% if it.profit_pct > 0 %}gain{% elif it.profit_pct < 0 %}loss{% endif %}">{{ it.profit_pct_str }}</td>
        </tr>
        {% endfor %}
    </table>
    <div class="summary">
        <div class="summary-row">
            <span>長債總市值</span><span class="right"><b>{{ '%.2f' % long_term_bonds_total_market_value_usd }}</b> USD ({{ '%.0f' % (long_term_bonds_total_market_value_usd * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>長債總成本</span><span class="right"><b>{{ '%.2f' % long_term_bonds_total_cost_usd }}</b> USD ({{ '%.0f' % (long_term_bonds_total_cost_usd * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>長債總報酬</span>
            <span class="right {% if long_term_bonds_total_profit_pct > 0 %}gain{% elif long_term_bonds_total_profit_pct < 0 %}loss{% endif %}">
                <b>{{ '%.2f' % long_term_bonds_total_profit_usd }}</b> USD ({{ '%.0f' % (long_term_bonds_total_profit_usd * exchange_rate) }} TWD, {{ '%.2f' % long_term_bonds_total_profit_pct }}%)
            </span>
        </div>
    </div>

    <h2>現金 (Cash)</h2>
    <table>
        <tr>
            <th>幣別</th><th class="right">餘額</th><th class="right">市值 (TWD)</th>
        </tr>
        {% for it in cash_table %}
        <tr>
            <td>{{ it.currency }}</td><td class="right">{{ it.amount_str }}</td><td class="right">{{ it.mv_twd_str }}</td>
        </tr>
        {% endfor %}
    </table>
    <div class="summary">
        <div class="summary-row">
            <span>現金總額 (TWD)</span><span class="right"><b>{{ '%.0f' % cash_total_value_twd }}</b> TWD</span>
        </div>
    </div>

    <h2>加密資產 (Crypto)</h2>
    <table>
        <tr>
            <th>代號</th><th class="right">現價 (USD)</th><th class="right">成本 (USD)</th><th class="right">持有數量</th><th class="right">市值 (USD)</th><th class="right">個別報酬</th>
        </tr>
        {% for it in crypto_table %}
        <tr>
            <td>{{ it.symbol }}</td><td class="right">{{ it.price_str }}</td><td class="right">{{ it.cost_str }}</td><td class="right">{{ it.amount_str }}</td><td class="right">{{ it.mv_str }}</td><td class="right {% if it.profit_pct > 0 %}gain{% elif it.profit_pct < 0 %}loss{% endif %}">{{ it.profit_pct_str }}</td>
        </tr>
        {% endfor %}
    </table>
    <div class="summary">
        <div class="summary-row">
            <span>加密資產總市值</span><span class="right"><b>{{ '%.2f' % crypto_total_market_value_usd }}</b> USD ({{ '%.0f' % (crypto_total_market_value_usd * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>加密資產總成本</span><span class="right"><b>{{ '%.2f' % crypto_total_cost_usd }}</b> USD ({{ '%.0f' % (crypto_total_cost_usd * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>加密資產總報酬</span>
            <span class="right {% if crypto_total_profit_pct > 0 %}gain{% elif crypto_total_profit_pct < 0 %}loss{% endif %}">
                <b>{{ '%.2f' % crypto_total_profit_usd }}</b> USD ({{ '%.0f' % (crypto_total_profit_usd * exchange_rate) }} TWD, {{ '%.2f' % crypto_total_profit_pct }}%)
            </span>
        </div>
    </div>

</div>
<script>
document.addEventListener('DOMContentLoaded', function () {
    Chart.register(ChartDataLabels);
    const assetCtx = document.getElementById('assetAllocationChart').getContext('2d');
    const assetData = {
        labels: ['股票', '現金', '加密資產', '黃金', '短債', '長債'],
        datasets: [{
            label: '資產配置 (TWD)',
            data: [
                {{ total_stock_value_twd or 0 }},
                {{ cash_total_value_twd or 0 }},
                {{ total_crypto_value_twd or 0 }},
                {{ gold_total_value_twd or 0 }},
                {{ short_term_bonds_total_value_twd or 0 }},
                {{ long_term_bonds_total_value_twd or 0 }}
            ],
            backgroundColor: [
                'rgba(75, 192, 192, 0.7)',
                'rgba(54, 162, 235, 0.7)',
                'rgba(255, 206, 86, 0.7)',
                'rgba(255, 99, 132, 0.7)',
                'rgba(153, 102, 255, 0.7)',
                'rgba(255, 159, 64, 0.7)'
            ],
            borderColor: '#fff',
            borderWidth: 2
        }]
    };
    new Chart(assetCtx, {
        type: 'pie',
        data: assetData,
        options: {
            responsive: true,
            plugins: {
                legend: { position: 'top' },
                title: { display: true, text: '資產配置 (TWD)', font: { size: 18 } },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let label = context.label ? context.label + ': ' : '';
                            if (context.parsed !== null) {
                                const total = context.chart.data.datasets[0].data.reduce((a, b) => a + b, 0);
                                const pct = total ? (context.parsed / total * 100).toFixed(2) : '0.00';
                                label += new Intl.NumberFormat('en-US', { style: 'currency', currency: 'TWD', maximumFractionDigits: 0 }).format(context.parsed);
                                label += ` (${pct}%)`;
                            }
                            return label;
                        }
                    }
                },
                datalabels: {
                    formatter: (value, ctx) => {
                        const total = ctx.chart.data.datasets[0].data.reduce((a, b) => a + b, 0);
                        if (!total) return '0%';
                        const pct = value / total * 100;
                        return pct > 2 ? pct.toFixed(1) + '%' : '';
                    },
                    color: '#fff',
                    font: { weight: 'bold', size: 14 },
                    textStrokeColor: '#333',
                    textStrokeWidth: 2
                }
            }
        },
    });

    const usCtx = document.getElementById('usGroupChart').getContext('2d');
    const usData = {
        labels: ['電力/能源', '指數', '防禦性消費', '科技/其他'],
        datasets: [{
            label: '美股配置 (USD)',
            data: [
                {{ power_total_usd or 0 }},
                {{ index_total_usd or 0 }},
                {{ defense_total_usd or 0 }},
                {{ tech_other_total_usd or 0 }}
            ],
            backgroundColor: [
                'rgba(255, 159, 64, 0.7)',
                'rgba(54, 162, 235, 0.7)',
                'rgba(75, 192, 192, 0.7)',
                'rgba(153, 102, 255, 0.7)'
            ],
            borderColor: '#fff',
            borderWidth: 2
        }]
    };
    new Chart(usCtx, {
        type: 'pie',
        data: usData,
        options: {
            responsive: true,
            plugins: {
                legend: { position: 'top' },
                title: { display: true, text: '美股：資產配置 (USD)', font: { size: 18 } },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let label = context.label ? context.label + ': ' : '';
                            if (context.parsed !== null) {
                                const total = context.chart.data.datasets[0].data.reduce((a,b)=>a+b,0);
                                const pct = total ? (context.parsed/total*100).toFixed(2) : '0.00';
                                label += new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(context.parsed);
                                label += ` (${pct}%)`;
                            }
                            return label;
                        }
                    }
                },
                datalabels: {
                    formatter: (value, ctx) => {
                        const total = ctx.chart.data.datasets[0].data.reduce((a,b)=>a+b,0);
                        if (!total) return '0%';
                        const pct = value / total * 100;
                        return pct > 2 ? pct.toFixed(1) + '%' : '';
                    },
                    color: '#fff',
                    font: { weight: 'bold', size: 14 },
                    textStrokeColor: '#333',
                    textStrokeWidth: 2
                }
            }
        }
    });

    // ETF toggle (client side only)
    const toggle = document.getElementById('toggleEtf');
    const rows = Array.from(document.querySelectorAll('[data-us-row]'));
    const usTotals = {
        all: {
            mvUsd: "{{ us_total_market_value_usd_str }}",
            mvTwd: "{{ us_total_market_value_twd_str }}",
            costUsd: "{{ us_total_cost_usd_str }}",
            costTwd: "{{ us_total_cost_twd_str }}",
            profitUsd: "{{ us_total_profit_usd_str }}",
            profitTwd: "{{ us_total_profit_twd_str }}",
            profitPct: "{{ us_total_profit_pct_str }}"
        },
        core: {
            mvUsd: "{{ us_core_total_market_value_usd_str }}",
            mvTwd: "{{ us_core_total_market_value_twd_str }}",
            costUsd: "{{ us_core_total_cost_usd_str }}",
            costTwd: "{{ us_core_total_cost_twd_str }}",
            profitUsd: "{{ us_core_total_profit_usd_str }}",
            profitTwd: "{{ us_core_total_profit_twd_str }}",
            profitPct: "{{ us_core_total_profit_pct_str }}"
        }
    };
    function refreshUsTable() {
        const hideEtf = toggle.checked;
        rows.forEach(row => {
            const isEtf = row.dataset.etf === '1';
            row.style.display = hideEtf && isEtf ? 'none' : '';
            const weightCell = row.querySelector('.weight-cell');
            const weightVal = hideEtf ? row.dataset.weightCore : row.dataset.weightAll;
            if (weightCell && weightVal) weightCell.textContent = weightVal;
        });
        const mode = hideEtf ? 'core' : 'all';
        document.getElementById('usTotalMVUSD').textContent = usTotals[mode].mvUsd;
        document.getElementById('usTotalMVTWD').textContent = usTotals[mode].mvTwd;
        document.getElementById('usTotalCostUSD').textContent = usTotals[mode].costUsd;
        document.getElementById('usTotalCostTWD').textContent = usTotals[mode].costTwd;
        document.getElementById('usTotalProfitUSD').textContent = usTotals[mode].profitUsd;
        document.getElementById('usTotalProfitTWD').textContent = usTotals[mode].profitTwd;
        document.getElementById('usTotalProfitPct').textContent = usTotals[mode].profitPct;
    }
    toggle.addEventListener('change', refreshUsTable);
    refreshUsTable();
});
</script>
</body>
</html>
"""

def _fmt_amount(value: float, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f}"


def process_usd_asset_portfolio(
    portfolio: List[Dict],
    price_fetcher: Callable[[str], float],
    amount_key: str = "shares",
) -> Dict:
    items = []
    for row in portfolio:
        price = price_fetcher(row["symbol"])
        cost_total = row["cost"] * row[amount_key]
        if price == "N/A" or cost_total == 0:
            mv, profit_pct = 0.0, 0.0
        else:
            mv = price * row[amount_key]
            profit_pct = (mv - cost_total) / cost_total * 100
        items.append(
            {
                "symbol": row["symbol"],
                "price": price,
                amount_key: row[amount_key],
                "cost": row["cost"],
                "market_value": mv,
                "profit_pct": profit_pct,
            }
        )

    total_market_value = sum(it["market_value"] for it in items)
    total_cost = sum(r["cost"] * r[amount_key] for r in portfolio)
    total_profit = total_market_value - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost else 0.0

    table_items = []
    for it in items:
        pretty_amount = f"{it[amount_key]:,.4f}".rstrip("0").rstrip(".")
        table_items.append(
            {
                **it,
                "price_str": f"{it['price']:,.2f}" if it["price"] != "N/A" else "N/A",
                "cost_str": f"{it['cost']:,.2f}",
                f"{amount_key}_str": pretty_amount,
                "mv_str": f"{it['market_value']:,.2f}",
                "profit_pct_str": f"{it['profit_pct']:.2f}%" if it["price"] != "N/A" else "N/A",
            }
        )

    table_items.sort(key=lambda x: x["market_value"], reverse=True)

    if amount_key == "amount":
        for item in table_items:
            item["amount_str"] = item[f"{amount_key}_str"]
    else:
        for item in table_items:
            item["shares_str"] = item[f"{amount_key}_str"]

    return {
        "table": table_items,
        "total_market_value_usd": total_market_value,
        "total_cost_usd": total_cost,
        "total_profit_usd": total_profit,
        "total_profit_pct": total_profit_pct,
    }


def build_context(hide_etf: bool = False) -> Dict:
    updated_at_tw = datetime.now(timezone("Asia/Taipei")).strftime("%Y-%m-%d %H:%M:%S")
    exchange_rate = get_currency_rate("USDTWD", default=32.5)

    us_data = process_usd_asset_portfolio(US_PORTFOLIO, cached_close)
    us_total_market_value = us_data["total_market_value_usd"]
    us_total_cost = us_data["total_cost_usd"]
    us_total_profit = us_data["total_profit_usd"]
    us_total_profit_pct = us_data["total_profit_pct"]

    power_total_usd = 0.0
    index_total_usd = 0.0
    defense_total_usd = 0.0
    tech_other_total_usd = 0.0
    for it in us_data["table"]:
        sym = it["symbol"]
        mv = it["market_value"]
        if sym in US_GROUP_POWER:
            power_total_usd += mv
        elif sym in US_GROUP_INDEX:
            index_total_usd += mv
        elif sym in US_GROUP_DEFENSE:
            defense_total_usd += mv
        else:
            tech_other_total_usd += mv

    us_core_items = [it for it in us_data["table"] if it["symbol"] not in EXCLUDED_ETFS_US]
    us_core_total_market_value = sum(it["market_value"] for it in us_core_items)
    us_core_total_cost = sum(r["cost"] * r["shares"] for r in US_PORTFOLIO if r["symbol"] not in EXCLUDED_ETFS_US)
    us_core_total_profit = us_core_total_market_value - us_core_total_cost
    us_core_total_profit_pct = (us_core_total_profit / us_core_total_cost * 100) if us_core_total_cost else 0.0

    us_denominator_all = us_total_market_value or 1
    us_denominator_core = us_core_total_market_value or 1
    us_table: List[Dict] = []
    for it in us_data["table"]:
        is_excluded = it["symbol"] in EXCLUDED_ETFS_US
        weight_all_pct = it["market_value"] / us_denominator_all * 100 if us_denominator_all else 0
        weight_core_pct = 0 if is_excluded else it["market_value"] / us_denominator_core * 100
        weight_display = weight_core_pct if hide_etf else weight_all_pct
        us_table.append(
            {
                **it,
                "is_excluded": is_excluded,
                "weight_all_pct": weight_all_pct,
                "weight_core_pct": weight_core_pct,
                "weight_all_pct_str": f"{weight_all_pct:.2f}%",
                "weight_core_pct_str": f"{weight_core_pct:.2f}%",
                "weight_display": f"{weight_display:.2f}%",
            }
        )

    if hide_etf:
        us_table = [it for it in us_table if not it["is_excluded"]]

    tw_items = []
    for row in TW_PORTFOLIO:
        price = get_tw_stock_price(row["symbol"])
        cost_total = row["cost"] * row["shares"]
        if price == "N/A" or cost_total == 0:
            mv, profit_pct = 0.0, 0.0
        else:
            mv = price * row["shares"]
            profit_pct = ((price * row["shares"]) - cost_total) / cost_total * 100
        tw_items.append(
            {"symbol": row["symbol"], "price": price, "shares": row["shares"], "cost": row["cost"], "market_value": mv, "profit_pct": profit_pct}
        )
    tw_total_market_value = sum(it["market_value"] for it in tw_items)
    tw_total_cost = sum(r["cost"] * r["shares"] for r in TW_PORTFOLIO)
    tw_total_profit = tw_total_market_value - tw_total_cost
    tw_total_profit_pct = (tw_total_profit / tw_total_cost * 100) if tw_total_cost else 0.0
    tw_denominator = tw_total_market_value or 1
    tw_table = []
    for it in tw_items:
        tw_table.append(
            {
                **it,
                "price_str": f"{it['price']:.2f}" if it["price"] != "N/A" else "N/A",
                "cost_str": f"{it['cost']:.2f}",
                "shares_str": f"{it['shares']:,}".rstrip("0").rstrip("."),
                "mv_str": f"{it['market_value']:,.0f}",
                "profit_pct_str": f"{it['profit_pct']:.2f}%" if it["price"] != "N/A" else "N/A",
                "weight_str": f"{(it['market_value']/tw_denominator*100):.2f}%",
            }
        )
    tw_table.sort(key=lambda x: x["market_value"], reverse=True)

    short_term_bonds_data = process_usd_asset_portfolio(SHORT_TERM_BONDS, cached_close)
    long_term_bonds_data = process_usd_asset_portfolio(LONG_TERM_BONDS, cached_close)
    crypto_data = process_usd_asset_portfolio(CRYPTO_PORTFOLIO, get_crypto_price, amount_key="amount")
    gold_data = process_usd_asset_portfolio(GOLD_PORTFOLIO, cached_close)

    cash_table = []
    cash_total_value_twd = 0.0
    for row in CASH_HOLDINGS:
        rate = 1.0 if row["currency"] == "TWD" else get_currency_rate(f"{row['currency']}TWD", 1.0)
        mv_twd = row["amount"] * rate
        cash_total_value_twd += mv_twd
        cash_table.append({"currency": row["currency"], "amount_str": f"{row['amount']:,.2f}", "mv_twd_str": f"{mv_twd:,.0f}"})

    total_stock_value_twd = (us_total_market_value * exchange_rate) + tw_total_market_value
    short_term_bonds_total_value_twd = short_term_bonds_data["total_market_value_usd"] * exchange_rate
    long_term_bonds_total_value_twd = long_term_bonds_data["total_market_value_usd"] * exchange_rate
    total_crypto_value_twd = crypto_data["total_market_value_usd"] * exchange_rate
    gold_total_value_twd = gold_data["total_market_value_usd"] * exchange_rate

    grand_total_market_value_twd = (
        total_stock_value_twd
        + cash_total_value_twd
        + total_crypto_value_twd
        + short_term_bonds_total_value_twd
        + long_term_bonds_total_value_twd
        + gold_total_value_twd
    )

    grand_total_cost_twd = (
        (us_total_cost * exchange_rate)
        + tw_total_cost
        + (short_term_bonds_data["total_cost_usd"] * exchange_rate)
        + (long_term_bonds_data["total_cost_usd"] * exchange_rate)
        + cash_total_value_twd
        + (crypto_data["total_cost_usd"] * exchange_rate)
        + (gold_data["total_cost_usd"] * exchange_rate)
    )

    grand_total_profit_twd = grand_total_market_value_twd - grand_total_cost_twd
    grand_total_profit_pct = (grand_total_profit_twd / grand_total_cost_twd * 100) if grand_total_cost_twd else 0.0

    template_args = {
        "updated_at": updated_at_tw,
        "exchange_rate": exchange_rate,
        "excluded_join": ", ".join(sorted(EXCLUDED_ETFS_US)),
        "initial_hide_etf": hide_etf,
        "us_table": us_table,
        "us_total_market_value": us_total_market_value,
        "us_total_cost": us_total_cost,
        "us_total_profit": us_total_profit,
        "us_total_profit_pct": us_total_profit_pct,
        "us_core_total_market_value": us_core_total_market_value,
        "us_core_total_cost": us_core_total_cost,
        "us_core_total_profit": us_core_total_profit,
        "us_core_total_profit_pct": us_core_total_profit_pct,
        "tw_table": tw_table,
        "tw_total_market_value": tw_total_market_value,
        "tw_total_cost": tw_total_cost,
        "tw_total_profit": tw_total_profit,
        "tw_total_profit_pct": tw_total_profit_pct,
        "cash_table": cash_table,
        "cash_total_value_twd": cash_total_value_twd,
        "total_stock_value_twd": total_stock_value_twd,
        "total_crypto_value_twd": total_crypto_value_twd,
        "short_term_bonds_total_value_twd": short_term_bonds_total_value_twd,
        "long_term_bonds_total_value_twd": long_term_bonds_total_value_twd,
        "gold_total_value_twd": gold_total_value_twd,
        "grand_total_market_value_twd": grand_total_market_value_twd,
        "grand_total_cost_twd": grand_total_cost_twd,
        "grand_total_profit_twd": grand_total_profit_twd,
        "grand_total_profit_pct": grand_total_profit_pct,
        "power_total_usd": power_total_usd,
        "index_total_usd": index_total_usd,
        "defense_total_usd": defense_total_usd,
        "tech_other_total_usd": tech_other_total_usd,
        "us_total_market_value_usd_str": _fmt_amount(us_total_market_value, 2),
        "us_total_market_value_twd_str": _fmt_amount(us_total_market_value * exchange_rate, 0),
        "us_total_cost_usd_str": _fmt_amount(us_total_cost, 2),
        "us_total_cost_twd_str": _fmt_amount(us_total_cost * exchange_rate, 0),
        "us_total_profit_usd_str": _fmt_amount(us_total_profit, 2),
        "us_total_profit_twd_str": _fmt_amount(us_total_profit * exchange_rate, 0),
        "us_total_profit_pct_str": f"{us_total_profit_pct:.2f}%",
        "us_core_total_market_value_usd_str": _fmt_amount(us_core_total_market_value, 2),
        "us_core_total_market_value_twd_str": _fmt_amount(us_core_total_market_value * exchange_rate, 0),
        "us_core_total_cost_usd_str": _fmt_amount(us_core_total_cost, 2),
        "us_core_total_cost_twd_str": _fmt_amount(us_core_total_cost * exchange_rate, 0),
        "us_core_total_profit_usd_str": _fmt_amount(us_core_total_profit, 2),
        "us_core_total_profit_twd_str": _fmt_amount(us_core_total_profit * exchange_rate, 0),
        "us_core_total_profit_pct_str": f"{us_core_total_profit_pct:.2f}%",
    }

    for prefix, data_dict in [
        ("short_term_bonds", short_term_bonds_data),
        ("long_term_bonds", long_term_bonds_data),
        ("crypto", crypto_data),
        ("gold", gold_data),
    ]:
        for key, value in data_dict.items():
            template_args[f"{prefix}_{key}"] = value

    return template_args


def render_portfolio_page(hide_etf: bool = False) -> str:
    ctx = build_context(hide_etf=hide_etf)
    template = app.jinja_env.from_string(TEMPLATE)
    return template.render(**ctx)


def build_static_site(output_path: str = "docs/index.html", hide_etf: bool = False) -> str:
    with app.app_context():
        html = render_portfolio_page(hide_etf=hide_etf)
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


@app.route("/")
def home():
    hide_etf = request.args.get("hide_etf") in ("1", "true", "on", "yes")
    return render_portfolio_page(hide_etf=hide_etf)


@app.get("/health")
def health():
    return {"status": "ok"}


def main():
    parser = argparse.ArgumentParser(description="Portfolio dashboard / static site generator")
    parser.add_argument("--output", help="輸出靜態 HTML 路徑（例如 docs/index.html 供 GitHub Pages）")
    parser.add_argument("--serve", action="store_true", help="啟動本地 Flask 伺服器")
    parser.add_argument("--hide-etf", action="store_true", help="預設隱藏 ETF")
    args = parser.parse_args()

    if args.output:
        path = build_static_site(output_path=args.output, hide_etf=args.hide_etf)
        print(f"Static site generated at {path}")
        if not args.serve:
            return

    # 若未指定 --output，預設直接啟動伺服器
    if args.serve or not args.output:
        port = int(os.environ.get("PORT", 5000))
        app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
