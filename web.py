# -*- coding: utf-8 -*-
"""
本機：
  pip install flask yfinance
  python portfolio.py
開啟：http://127.0.0.1:5000/

Render（建議 Start Command）：
  gunicorn portfolio:app --bind 0.0.0.0:$PORT --access-logfile - --error-logfile - --timeout 120 --forwarded-allow-ips='*'
"""

from flask import Flask, render_template_string, request
from datetime import datetime
from werkzeug.middleware.proxy_fix import ProxyFix
import yfinance as yf
import pandas as pd
import threading, time, os, logging
from pytz import timezone

app = Flask(__name__)
# 代理相容（雲端反向代理下正確判斷 https/host）
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# 降噪：隱藏 yfinance 的「possibly delisted」等訊息
logging.getLogger("yfinance").setLevel(logging.ERROR)

# ============== 使用者設定 ==============
# 在「自選股績效」中要排除的美股 ETF（用於 hide_etf 與摘要）
# SGOV, BOXX, TLT, GLD 已移至其專屬部位，故從此處移除
EXCLUDED_ETFS_US = {'VOO', 'VEA', 'EWT', 'XLU','AVDV','IDMO'}

# ---- 美股部位圓餅圖分類 ----
US_GROUP_POWER   = {'AEP','DUK','LEU','CEG','HUBB','ETN','VST','XLU'}
US_GROUP_INDEX   = {'VOO','VEA','EWT'}
US_GROUP_DEFENSE = {'UNH','KO','MCD','COST','GIS','YUM'}

# 你的持倉（可自行調整）
US_PORTFOLIO = [
    # ETF（會被排除）
    # {'symbol': 'SGOV',  'shares': 1100,  'cost': 100.40},
    {'symbol': 'VOO',   'shares': 70.00, 'cost': 506.75},
    {'symbol': 'VEA',   'shares': 86.80, 'cost': 53.55},
    # {'symbol': 'GLD',   'shares': 16.55, 'cost': 300.10},
    # {'symbol': 'TLT',   'shares': 224.7, 'cost': 92.22},
    # {'symbol': 'BOXX',  'shares': 100,   'cost': 110.71},
    {'symbol': 'XLU',   'shares': 250, 'cost': 42.854},
    {'symbol': 'EWT',   'shares': 100,   'cost': 61.27},
    # {'symbol': 'XLU',   'shares': 87.71, 'cost': 83.80},
    # {'symbol': 'VT',    'shares': 50,    'cost': 133.69},

    {'symbol': 'PYPL',  'shares': 35,    'cost': 68.855},
    {'symbol': 'TSM',   'shares': 32,     'cost': 284.1712},
    {'symbol': 'SNPS',  'shares': 4,     'cost': 397.15},
    {'symbol': 'YUM',   'shares': 1,     'cost': 141.34},
    # ===== 自選股（會顯示）=====
    {'symbol': 'UNH',   'shares': 22,    'cost': 310.86},
    {'symbol': 'GOOGL', 'shares': 73.80,    'cost': 176.454},
    {'symbol': 'NVDA',  'shares': 40.1387,    'cost': 133.039},
    {'symbol': 'MSTR',  'shares': 10,    'cost': 287.304},
    {'symbol': 'QCOM',  'shares': 12,     'cost': 161.4525},
    {'symbol': 'KO',    'shares': 67.47, 'cost': 67.96},
    {'symbol': 'AEP',   'shares': 14,    'cost': 104.502},
    {'symbol': 'DUK',   'shares': 15,    'cost': 115.8626},
    {'symbol': 'MCD',   'shares': 10,    'cost': 303.413},
    {'symbol': 'CEG',   'shares': 7,     'cost': 341.88},
    {'symbol': 'LEU',   'shares': 11,     'cost': 293.236},
    {'symbol': 'AMZN',   'shares': 15,     'cost': 220.637},
    {'symbol': 'COST',   'shares': 2,     'cost': 920.255},
    {'symbol': 'ETN',   'shares': 1,     'cost': 365.12},
    {'symbol': 'HUBB',   'shares': 4,     'cost': 413.425},
    {'symbol': 'META',   'shares': 12,     'cost': 713.02},
    # {'symbol': 'MU',   'shares': 8,     'cost': 168.81125},
    {'symbol': 'VST',   'shares': 4,     'cost': 204.68},
    {'symbol': 'BABA',   'shares': 2,     'cost': 169.42},
    {'symbol': 'EOSE',   'shares':11,     'cost': 13.331},
    {'symbol': 'FCX',   'shares': 3,     'cost': 41.6133},
    {'symbol': 'SMR',   'shares':10,     'cost': 19.55},

    {'symbol': 'GIS',   'shares': 2,     'cost': 49.695},
    # {'symbol': 'IDMO',   'shares': 60,     'cost': 53.48},

    {'symbol': 'INTC',   'shares': 19,     'cost': 37.003},
    {'symbol': 'UUUU',   'shares': 30,     'cost': 16.96},

    {'symbol': 'TSLA',   'shares': 1.473,     'cost': 423.885},
    {'symbol': 'VWO',   'shares': 60,     'cost': 54.74},

    # {'symbol': 'AVDV',   'shares': 40,     'cost':87.945},
]

TW_PORTFOLIO = [
    {'symbol': '0050.TW',   'shares': 10637, 'cost': 41.58},
    {'symbol': '006208.TW', 'shares': 9000,  'cost': 112.67},
    {'symbol': '00713.TW',  'shares': 10427, 'cost': 54.40},
]

# 黃金部位
GOLD_PORTFOLIO = [
    {'symbol': 'GLD',   'shares': 16.55, 'cost': 300.10},
]

# 短債部位
SHORT_TERM_BONDS = [
    {'symbol': 'SGOV',  'shares': 900,  'cost': 100.402495},
    {'symbol': 'BOXX',  'shares': 100,   'cost': 110.71},
]

# 長債部位
LONG_TERM_BONDS = [
    {'symbol': 'TLT',   'shares': 193, 'cost': 91.815},
    {'symbol': 'IEF',   'shares': 80, 'cost': 96.81275},

]

# 現金部位
CASH_HOLDINGS = [
    {'currency': 'TWD', 'amount': 500000},
    {'currency': 'AUD', 'amount': 6851.54},
    {'currency': 'JPY', 'amount': 417356},
    {'currency': 'USD', 'amount': 6314},
]

# 加密貨幣投資組合
CRYPTO_PORTFOLIO = [
    {'symbol': 'BTC', 'amount': 0.0142, 'cost': 116206},
    {'symbol': 'ETH', 'amount': 0.003, 'cost': 0.000000000001},
    {'symbol': 'USDT', 'amount': 455.944, 'cost': 1.0},
    {'symbol': 'USDC', 'amount': 1630, 'cost': 1.0}
]


# ============== 輕量 TTL 快取 ==============
_TTL_FAST   = 60      # 1 分鐘：即時／當日
_TTL_NORMAL = 300     # 5 分鐘：一般
_TTL_LONG   = 3600    # 1 小時：較長週期

_cache = {}
_cache_lock = threading.Lock()
def _now(): return time.time()
def _get_cache(key):
    with _cache_lock:
        return _cache.get(key)
def _set_cache(key, value):
    with _cache_lock:
        _cache[key] = value

def cached_history(symbol, *, period=None, start=None, end=None, ttl=_TTL_NORMAL):
    """以 TTL 記憶 yfinance history；抓失敗時回上次成功的舊值（stale）。"""
    key = ("history", symbol, period, start, end)
    entry = _get_cache(key)
    now = _now()
    if entry and (now - entry["ts"] < ttl) and entry["data"] is not None:
        return entry["data"]
    try:
        tkr = yf.Ticker(symbol)
        df = tkr.history(period=period) if period else tkr.history(start=start, end=end)
        _set_cache(key, {"ts": now, "data": df})
        return df
    except Exception:
        if entry and entry["data"] is not None:
            return entry["data"]
        return pd.DataFrame()

def cached_close(symbol, ttl=_TTL_FAST):
    """
    取最近一筆有效收盤價：先試 7d，再退 1mo；各自帶 TTL。
    避免假日／停牌導致 period='1d' 為空而報「可能下市」。
    """
    for period, t in (("7d", ttl), ("1mo", max(ttl, _TTL_NORMAL))):
        df = cached_history(symbol, period=period, ttl=t)
        if not df.empty and "Close" in df:
            close = df["Close"].dropna()
            if not close.empty:
                return float(close.iloc[-1])
    return 'N/A'

def get_tw_stock_price(symbol):
    """
    台股 ETF/股票的強韌代碼嘗試：.TW → .TWO → 裸代碼 → .TPE
    取最近有效收盤價（搭配 cached_close）。
    """
    base = symbol.replace(".TW", "")
    candidates = [f"{base}.TW", f"{base}.TWO", base, f"{base}.TPE"]
    seen = set()
    for sym in candidates:
        if sym in seen:
            continue
        seen.add(sym)
        price = cached_close(sym, ttl=_TTL_FAST)
        if price != 'N/A':
            return price
    return 'N/A'

def get_crypto_price(symbol):
    """取加密貨幣對 USD 的價格"""
    return cached_close(f"{symbol}-USD", ttl=_TTL_FAST)

def get_currency_rate(pair, default=1.0):
    """取匯率，例如 'USDTWD=X'"""
    for suffix in ['=X', '']:
        price = cached_close(f"{pair}{suffix}", ttl=_TTL_LONG)
        if price != 'N/A':
            return price
    return default

# ============== 模板（投資組合） ==============
TEMPLATE = r"""
<html>
<head>
    <meta charset="utf-8">
    <title>Ching's Portfolio</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js"></script>
    <style>
        body { font-family: "微軟正黑體", Arial, sans-serif; background: #f4f6f8; color: #333; }
        .container { max-width: 1200px; margin: 32px auto; background: #fff; padding: 28px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,.06); }
        h1, h2, h3 { margin: 0 0 8px; color: #2c3e50; }
        h2 { margin-top: 28px; border-bottom: 2px solid #eaecef; padding-bottom: 8px;}
        .meta { color: #6c757d; margin-bottom: 16px; }
        .bar { display:flex; justify-content: space-between; align-items:center; margin: 10px 0 18px; gap: 8px; flex-wrap: wrap; }
        .pill { background:#e3f2fd; color:#1976d2; padding:8px 12px; border-radius:999px; font-weight:600; }
        .summary { background:#f8f9fa; padding:18px; border-radius:10px; margin:18px 0; }
        .summary-row { display:flex; justify-content:space-between; margin:6px 0; font-size: 1.1em; }
        .chart-container { max-width: 450px; margin: 24px auto; }
        table { width:100%; border-collapse: collapse; margin-top: 14px; }
        th, td { border: 1px solid #eaecef; padding: 10px 12px; text-align: left; }
        th { background: #f0f3f6; font-weight: 600; }
        .right { text-align:right; }
        .gain { color:#c62828; font-weight:700; } /* 紅漲 */
        .loss { color:#2e7d32; font-weight:700; } /* 綠跌 */
        .nav { margin-bottom: 8px; }
        .nav a { margin-right: 14px; text-decoration:none; color:#1976d2; font-weight: 500;}
    </style>
</head>
<body>
<div class="container">
    <div class="nav">
        <a href="/">投資組合</a>
    </div>

    <h1>Ching's Portfolio</h1>
    <div class="meta">更新時間：{{ updated_at }}</div>
    <div class="meta">美金兌台幣匯率：<b>{{ '%.3f' % exchange_rate }}</b></div>

    <div class="summary">
        <div class="summary-row">
            <span>總資產市值 (TWD)：</span>
            <span class="right"><b>{{ '%.0f' % grand_total_market_value_twd }}</b></span>
        </div>
        <div class="summary-row">
            <span>總投入成本 (TWD)：</span>
            <span class="right"><b>{{ '%.0f' % grand_total_cost_twd }}</b></span>
        </div>
        <div class="summary-row">
            <span>總報酬 (TWD)：</span>
            <span class="right {% if grand_total_profit_twd > 0 %}gain{% elif grand_total_profit_twd < 0 %}loss{% endif %}">
                <b>{{ '%.0f' % grand_total_profit_twd }}</b> ({{ '%.2f' % grand_total_profit_pct }}%)
            </span>
        </div>
    </div>
    
    <div class="chart-container">
        <canvas id="assetAllocationChart"></canvas>
    </div>

    <!-- 新增：美股部位四大類圓餅圖 -->
    <div class="chart-container">
        <canvas id="usGroupChart"></canvas>
    </div>

    <h2>美股投資組合 (USD)</h2>
     <div class="bar">
        <div></div>
        <form method="get" id="filterForm">
            <label>
                <input type="checkbox" name="hide_etf" value="1" {% if hide_etf %}checked{% endif %} onchange="document.getElementById('filterForm').submit()">
                隱藏 ETF ({{ excluded_join }})
            </label>
        </form>
    </div>
    <table>
        <tr>
            <th>代碼</th><th class="right">現價</th><th class="right">成本價</th><th class="right">持有股數</th><th class="right">市值</th><th class="right">佔比 (依顯示)</th><th class="right">個別報酬率</th>
        </tr>
        {% for it in us_table %}
        <tr>
            <td>{{ it.symbol }}</td><td class="right">{{ it.price_str }}</td><td class="right">{{ it.cost_str }}</td><td class="right">{{ it.shares_str }}</td><td class="right">{{ it.mv_str }}</td><td class="right">{{ it.weight_str }}</td><td class="right {% if it.profit_pct > 0 %}gain{% elif it.profit_pct < 0 %}loss{% endif %}">{{ it.profit_pct_str }}</td>
        </tr>
        {% endfor %}
    </table>

    <div class="summary">
        <h3>美股總結 (全部持倉)</h3>
        <div class="summary-row">
            <span>總市值：</span><span class="right"><b>{{ '%.2f' % us_total_market_value }}</b> USD ({{ '%.0f' % (us_total_market_value * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>總成本：</span><span class="right"><b>{{ '%.2f' % us_total_cost }}</b> USD ({{ '%.0f' % (us_total_cost * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>總報酬：</span>
            <span class="right {% if us_total_profit_pct > 0 %}gain{% elif us_total_profit_pct < 0 %}loss{% endif %}">
                <b>{{ '%.2f' % us_total_profit }}</b> USD ({{ '%.0f' % (us_total_profit * exchange_rate) }} TWD, {{ '%.2f' % us_total_profit_pct }}%)
            </span>
        </div>
    </div>

    <div class="summary">
        <h3>美股自選股績效 (已扣除 {{ excluded_join }})</h3>
        <div class="summary-row">
            <span>總市值：</span><span class="right"><b>{{ '%.2f' % us_core_total_market_value }}</b> USD ({{ '%.0f' % (us_core_total_market_value * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>總成本：</span><span class="right"><b>{{ '%.2f' % us_core_total_cost }}</b> USD ({{ '%.0f' % (us_core_total_cost * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>總報酬：</span>
            <span class="right {% if us_core_total_profit_pct > 0 %}gain{% elif us_core_total_profit_pct < 0 %}loss{% endif %}">
                <b>{{ '%.2f' % us_core_total_profit }}</b> USD ({{ '%.0f' % (us_core_total_profit * exchange_rate) }} TWD, {{ '%.2f' % us_core_total_profit_pct }}%)
            </span>
        </div>
    </div>

    <h2>台股投資組合 (TWD)</h2>
    <table>
        <tr>
            <th>代碼</th><th class="right">現價</th><th class="right">成本價</th><th class="right">持有股數</th><th class="right">市值</th><th class="right">佔比</th><th class="right">個別報酬率</th>
        </tr>
        {% for it in tw_table %}
        <tr>
            <td>{{ it.symbol }}</td><td class="right">{{ it.price_str }}</td><td class="right">{{ it.cost_str }}</td><td class="right">{{ it.shares_str }}</td><td class="right">{{ it.mv_str }}</td><td class="right">{{ it.weight_str }}</td><td class="right {% if it.profit_pct > 0 %}gain{% elif it.profit_pct < 0 %}loss{% endif %}">{{ it.profit_pct_str }}</td>
        </tr>
        {% endfor %}
    </table>
    <div class="summary">
        <div class="summary-row">
            <span>台股總市值：</span><span class="right"><b>{{ '%.0f' % tw_total_market_value }}</b> TWD</span>
        </div>
        <div class="summary-row">
            <span>台股總成本：</span><span class="right"><b>{{ '%.0f' % tw_total_cost }}</b> TWD</span>
        </div>
        <div class="summary-row">
            <span>台股總報酬：</span>
            <span class="right {% if tw_total_profit_pct > 0 %}gain{% elif tw_total_profit_pct < 0 %}loss{% endif %}">
                <b>{{ '%.0f' % tw_total_profit }}</b> TWD ({{ '%.2f' % tw_total_profit_pct }}%)
            </span>
        </div>
    </div>

    <h2>黃金部位 (Gold)</h2>
    <table>
        <tr>
            <th>代碼</th><th class="right">現價 (USD)</th><th class="right">成本價 (USD)</th><th class="right">持有盎司/股數</th><th class="right">市值 (USD)</th><th class="right">個別報酬率</th>
        </tr>
        {% for it in gold_table %}
        <tr>
            <td>{{ it.symbol }}</td><td class="right">{{ it.price_str }}</td><td class="right">{{ it.cost_str }}</td><td class="right">{{ it.shares_str }}</td><td class="right">{{ it.mv_str }}</td><td class="right {% if it.profit_pct > 0 %}gain{% elif it.profit_pct < 0 %}loss{% endif %}">{{ it.profit_pct_str }}</td>
        </tr>
        {% endfor %}
    </table>
    <div class="summary">
        <div class="summary-row">
            <span>黃金總市值：</span><span class="right"><b>{{ '%.2f' % gold_total_market_value_usd }}</b> USD ({{ '%.0f' % (gold_total_market_value_usd * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>黃金總成本：</span><span class="right"><b>{{ '%.2f' % gold_total_cost_usd }}</b> USD ({{ '%.0f' % (gold_total_cost_usd * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>黃金總報酬：</span>
            <span class="right {% if gold_total_profit_pct > 0 %}gain{% elif gold_total_profit_pct < 0 %}loss{% endif %}">
                <b>{{ '%.2f' % gold_total_profit_usd }}</b> USD ({{ '%.0f' % (gold_total_profit_usd * exchange_rate) }} TWD, {{ '%.2f' % gold_total_profit_pct }}%)
            </span>
        </div>
    </div>

    <h2>短債部位 (Short-term Bonds)</h2>
    <table>
        <tr>
            <th>代碼</th><th class="right">現價 (USD)</th><th class="right">成本價 (USD)</th><th class="right">持有數量</th><th class="right">市值 (USD)</th><th class="right">個別報酬率</th>
        </tr>
        {% for it in short_term_bonds_table %}
        <tr>
            <td>{{ it.symbol }}</td><td class="right">{{ it.price_str }}</td><td class="right">{{ it.cost_str }}</td><td class="right">{{ it.shares_str }}</td><td class="right">{{ it.mv_str }}</td><td class="right {% if it.profit_pct > 0 %}gain{% elif it.profit_pct < 0 %}loss{% endif %}">{{ it.profit_pct_str }}</td>
        </tr>
        {% endfor %}
    </table>
    <div class="summary">
        <div class="summary-row">
            <span>短債總市值：</span><span class="right"><b>{{ '%.2f' % short_term_bonds_total_market_value_usd }}</b> USD ({{ '%.0f' % (short_term_bonds_total_market_value_usd * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>短債總成本：</span><span class="right"><b>{{ '%.2f' % short_term_bonds_total_cost_usd }}</b> USD ({{ '%.0f' % (short_term_bonds_total_cost_usd * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>短債總報酬：</span>
            <span class="right {% if short_term_bonds_total_profit_pct > 0 %}gain{% elif short_term_bonds_total_profit_pct < 0 %}loss{% endif %}">
                <b>{{ '%.2f' % short_term_bonds_total_profit_usd }}</b> USD ({{ '%.0f' % (short_term_bonds_total_profit_usd * exchange_rate) }} TWD, {{ '%.2f' % short_term_bonds_total_profit_pct }}%)
            </span>
        </div>
    </div>

    <h2>長債部位 (Long-term Bonds)</h2>
    <table>
        <tr>
            <th>代碼</th><th class="right">現價 (USD)</th><th class="right">成本價 (USD)</th><th class="right">持有數量</th><th class="right">市值 (USD)</th><th class="right">個別報酬率</th>
        </tr>
        {% for it in long_term_bonds_table %}
        <tr>
            <td>{{ it.symbol }}</td><td class="right">{{ it.price_str }}</td><td class="right">{{ it.cost_str }}</td><td class="right">{{ it.shares_str }}</td><td class="right">{{ it.mv_str }}</td><td class="right {% if it.profit_pct > 0 %}gain{% elif it.profit_pct < 0 %}loss{% endif %}">{{ it.profit_pct_str }}</td>
        </tr>
        {% endfor %}
    </table>
    <div class="summary">
        <div class="summary-row">
            <span>長債總市值：</span><span class="right"><b>{{ '%.2f' % long_term_bonds_total_market_value_usd }}</b> USD ({{ '%.0f' % (long_term_bonds_total_market_value_usd * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>長債總成本：</span><span class="right"><b>{{ '%.2f' % long_term_bonds_total_cost_usd }}</b> USD ({{ '%.0f' % (long_term_bonds_total_cost_usd * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>長債總報酬：</span>
            <span class="right {% if long_term_bonds_total_profit_pct > 0 %}gain{% elif long_term_bonds_total_profit_pct < 0 %}loss{% endif %}">
                <b>{{ '%.2f' % long_term_bonds_total_profit_usd }}</b> USD ({{ '%.0f' % (long_term_bonds_total_profit_usd * exchange_rate) }} TWD, {{ '%.2f' % long_term_bonds_total_profit_pct }}%)
            </span>
        </div>
    </div>

    <h2>現金部位 (Cash)</h2>
    <table>
        <tr>
            <th>幣別</th><th class="right">金額</th><th class="right">市值 (TWD)</th>
        </tr>
        {% for it in cash_table %}
        <tr>
            <td>{{ it.currency }}</td><td class="right">{{ it.amount_str }}</td><td class="right">{{ it.mv_twd_str }}</td>
        </tr>
        {% endfor %}
    </table>
    <div class="summary">
        <div class="summary-row">
            <span>現金總部位 (TWD)：</span><span class="right"><b>{{ '%.0f' % cash_total_value_twd }}</b> TWD</span>
        </div>
    </div>

    <h2>加密貨幣 (Crypto)</h2>
    <table>
        <tr>
            <th>代碼</th><th class="right">現價 (USD)</th><th class="right">成本價 (USD)</th><th class="right">持有數量</th><th class="right">市值 (USD)</th><th class="right">個別報酬率</th>
        </tr>
        {% for it in crypto_table %}
        <tr>
            <td>{{ it.symbol }}</td><td class="right">{{ it.price_str }}</td><td class="right">{{ it.cost_str }}</td><td class="right">{{ it.amount_str }}</td><td class="right">{{ it.mv_str }}</td><td class="right {% if it.profit_pct > 0 %}gain{% elif it.profit_pct < 0 %}loss{% endif %}">{{ it.profit_pct_str }}</td>
        </tr>
        {% endfor %}
    </table>
    <div class="summary">
        <div class="summary-row">
            <span>加密貨幣總市值：</span><span class="right"><b>{{ '%.2f' % crypto_total_market_value_usd }}</b> USD ({{ '%.0f' % (crypto_total_market_value_usd * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>加密貨幣總成本：</span><span class="right"><b>{{ '%.2f' % crypto_total_cost_usd }}</b> USD ({{ '%.0f' % (crypto_total_cost_usd * exchange_rate) }} TWD)</span>
        </div>
        <div class="summary-row">
            <span>加密貨幣總報酬：</span>
            <span class="right {% if crypto_total_profit_pct > 0 %}gain{% elif crypto_total_profit_pct < 0 %}loss{% endif %}">
                <b>{{ '%.2f' % crypto_total_profit_usd }}</b> USD ({{ '%.0f' % (crypto_total_profit_usd * exchange_rate) }} TWD, {{ '%.2f' % crypto_total_profit_pct }}%)
            </span>
        </div>
    </div>

</div>
<script>
document.addEventListener('DOMContentLoaded', function () {
    Chart.register(ChartDataLabels);
    const ctx = document.getElementById('assetAllocationChart').getContext('2d');
    const data = {
        labels: ['股票', '現金', '加密貨幣', '黃金', '短債', '長債'],
        datasets: [{
            label: '資產分佈 (TWD)',
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
    const config = {
        type: 'pie',
        data: data,
        options: {
            responsive: true,
            plugins: {
                legend: {
                    position: 'top',
                },
                title: {
                    display: true,
                    text: '資產分佈 (TWD)',
                    font: { size: 18 }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let label = context.label || '';
                            if (label) { label += ': '; }
                            if (context.parsed !== null) {
                                const total = context.chart.data.datasets[0].data.reduce((a, b) => a + b, 0);
                                const percentage = ((context.parsed / total) * 100).toFixed(2);
                                label += new Intl.NumberFormat('en-US', { style: 'currency', currency: 'TWD', maximumFractionDigits: 0 }).format(context.parsed) + ` (${percentage}%)`;
                            }
                            return label;
                        }
                    }
                },
                datalabels: {
                    formatter: (value, ctx) => {
                        const total = ctx.chart.data.datasets[0].data.reduce((a, b) => a + b, 0);
                        if (total === 0) return '0%';
                        const percentage = value / total * 100;
                        return percentage > 2 ? percentage.toFixed(1) + '%' : '';
                    },
                    color: '#fff',
                    font: {
                        weight: 'bold',
                        size: 14,
                    },
                    textStrokeColor: '#333',
                    textStrokeWidth: 2
                }
            }
        },
    };
    new Chart(ctx, config);

    // ===== 美股部位四大類圓餅圖 =====
    const ctxUS = document.getElementById('usGroupChart').getContext('2d');
    const usData = {
        labels: ['電力股', '指數投資', '防禦股', '科技股(其他)'],
        datasets: [{
            label: '美股部位 (USD)',
            data: [
                {{ power_total_usd or 0 }},
                {{ index_total_usd or 0 }},
                {{ defense_total_usd or 0 }},
                {{ tech_other_total_usd or 0 }}
            ],
            backgroundColor: [
                'rgba(255, 159, 64, 0.7)',   // 電力
                'rgba(54, 162, 235, 0.7)',   // 指數
                'rgba(75, 192, 192, 0.7)',   // 防禦
                'rgba(153, 102, 255, 0.7)'   // 科技(其他)
            ],
            borderColor: '#fff',
            borderWidth: 2
        }]
    };
    const usConfig = {
        type: 'pie',
        data: usData,
        options: {
            responsive: true,
            plugins: {
                legend: { position: 'top' },
                title: {
                    display: true,
                    text: '美股部位：產業/性質分類 (USD)',
                    font: { size: 18 }
                },
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
    };
    new Chart(ctxUS, usConfig);
});
</script>
</body>
</html>
"""

# ============== Helper Function ==============
def process_usd_asset_portfolio(portfolio, price_fetcher, amount_key='shares'):
    """通用函式，處理以美元計價的資產組合"""
    items = []
    for row in portfolio:
        price = price_fetcher(row['symbol'])
        cost_total = row['cost'] * row[amount_key]
        if price == 'N/A' or cost_total == 0:
            mv, profit_pct = 0.0, 0.0
        else:
            mv = price * row[amount_key]
            profit_pct = (mv - cost_total) / cost_total * 100
        items.append({"symbol": row['symbol'], "price": price, amount_key: row[amount_key],"cost": row['cost'], "market_value": mv, "profit_pct": profit_pct})
    
    total_market_value = sum(it["market_value"] for it in items)
    total_cost = sum(r['cost'] * r[amount_key] for r in portfolio)
    total_profit = total_market_value - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost else 0.0
    
    table_items = []
    for it in items:
        table_items.append({
            **it,
            "price_str": f"{it['price']:,.2f}" if it['price'] != 'N/A' else 'N/A',
            "cost_str": f"{it['cost']:,.2f}",
            f"{amount_key}_str": f"{it[amount_key]:,.4f}".rstrip('0').rstrip('.'),
            "mv_str": f"{it['market_value']:,.2f}",
            "profit_pct_str": f"{it['profit_pct']:.2f}%" if it['price'] != 'N/A' else 'N/A',
        })
    table_items.sort(key=lambda x: x["market_value"], reverse=True)

    # 為了讓模板的 key 一致，統一命名為 'shares_str' 或 'amount_str' 供 HTML 使用
    if amount_key == 'amount':
        for item in table_items:
            item['amount_str'] = item[f'{amount_key}_str']
    else: # 預設為 shares
        for item in table_items:
            item['shares_str'] = item[f'{amount_key}_str']

    return {
        "table": table_items,
        "total_market_value_usd": total_market_value,
        "total_cost_usd": total_cost,
        "total_profit_usd": total_profit,
        "total_profit_pct": total_profit_pct
    }


# ============== 路由 ==============
@app.route("/")
def home():
    updated_at_tw = datetime.now(timezone('Asia/Taipei')).strftime("%Y-%m-%d %H:%M:%S")
    exchange_rate = get_currency_rate('USDTWD', default=32.5)

    # ---- 美股資料
    us_data = process_usd_asset_portfolio(US_PORTFOLIO, cached_close)
    us_total_market_value = us_data['total_market_value_usd']
    us_total_cost = us_data['total_cost_usd']
    us_total_profit = us_data['total_profit_usd']
    us_total_profit_pct = us_data['total_profit_pct']

    # ---- 美股部位四大類（以全部美股持倉計算，含 ETF；單位 USD）
    power_total_usd = 0.0
    index_total_usd = 0.0
    defense_total_usd = 0.0
    tech_other_total_usd = 0.0
    for it in us_data['table']:  # it: {'symbol','market_value',...}
        sym = it['symbol']
        mv  = it['market_value']
        if sym in US_GROUP_POWER:
            power_total_usd += mv
        elif sym in US_GROUP_INDEX:
            index_total_usd += mv
        elif sym in US_GROUP_DEFENSE:
            defense_total_usd += mv
        else:
            tech_other_total_usd += mv

    # ===== 美股「自選股」摘要（排除 ETF）=====
    us_core_items = [it for it in us_data['table'] if it["symbol"] not in EXCLUDED_ETFS_US]
    us_core_total_market_value = sum(it["market_value"] for it in us_core_items)
    us_core_total_cost = sum(r['cost'] * r['shares'] for r in US_PORTFOLIO if r['symbol'] not in EXCLUDED_ETFS_US)
    us_core_total_profit = us_core_total_market_value - us_core_total_cost
    us_core_total_profit_pct = (us_core_total_profit / us_core_total_cost * 100) if us_core_total_cost else 0.0

    # 切換：隱藏 ETF（影響表格與佔比分母）
    hide_etf = request.args.get('hide_etf') in ('1', 'true', 'on', 'yes')
    us_table_src = us_core_items if hide_etf else us_data['table']
    us_denominator = sum(it["market_value"] for it in us_table_src) or 1
    for it in us_table_src:
        it["weight_str"] = f"{(it['market_value'] / us_denominator * 100):.2f}%"
    us_table = us_table_src

    # ---- 台股資料
    tw_items = []
    for row in TW_PORTFOLIO:
        price = get_tw_stock_price(row['symbol'])
        cost_total = row['cost'] * row['shares']
        if price == 'N/A' or cost_total == 0: mv, profit_pct = 0.0, 0.0
        else: mv, profit_pct = price * row['shares'], ((price * row['shares']) - cost_total) / cost_total * 100
        tw_items.append({"symbol": row['symbol'], "price": price, "shares": row['shares'], "cost": row['cost'], "market_value": mv, "profit_pct": profit_pct})
    tw_total_market_value = sum(it["market_value"] for it in tw_items)
    tw_total_cost = sum(r['cost'] * r['shares'] for r in TW_PORTFOLIO)
    tw_total_profit = tw_total_market_value - tw_total_cost
    tw_total_profit_pct = (tw_total_profit / tw_total_cost * 100) if tw_total_cost else 0.0
    tw_denominator = tw_total_market_value or 1
    tw_table = []
    for it in tw_items:
        tw_table.append({**it, "price_str": f"{it['price']:.2f}" if it['price']!='N/A' else 'N/A', "cost_str": f"{it['cost']:.2f}", "shares_str": f"{it['shares']:,}".rstrip('0').rstrip('.'), "mv_str": f"{it['market_value']:,.0f}", "profit_pct_str": f"{it['profit_pct']:.2f}%" if it['price']!='N/A' else 'N/A', "weight_str": f"{(it['market_value']/tw_denominator*100):.2f}%"})
    tw_table.sort(key=lambda x: x["market_value"], reverse=True)

    # ---- 債券 & 加密貨幣 & 現金 & 黃金
    short_term_bonds_data = process_usd_asset_portfolio(SHORT_TERM_BONDS, cached_close)
    long_term_bonds_data = process_usd_asset_portfolio(LONG_TERM_BONDS, cached_close)
    crypto_data = process_usd_asset_portfolio(CRYPTO_PORTFOLIO, get_crypto_price, amount_key='amount')
    gold_data = process_usd_asset_portfolio(GOLD_PORTFOLIO, cached_close)
    
    cash_table = []
    cash_total_value_twd = 0.0
    for row in CASH_HOLDINGS:
        rate = 1.0 if row['currency'] == 'TWD' else get_currency_rate(f"{row['currency']}TWD", 1.0)
        mv_twd = row['amount'] * rate
        cash_total_value_twd += mv_twd
        cash_table.append({"currency": row['currency'], "amount_str": f"{row['amount']:,.2f}", "mv_twd_str": f"{mv_twd:,.0f}"})
    
    # ---- 總覽（折台幣）
    total_stock_value_twd = (us_total_market_value * exchange_rate) + tw_total_market_value
    short_term_bonds_total_value_twd = short_term_bonds_data['total_market_value_usd'] * exchange_rate
    long_term_bonds_total_value_twd = long_term_bonds_data['total_market_value_usd'] * exchange_rate
    total_crypto_value_twd = crypto_data['total_market_value_usd'] * exchange_rate
    gold_total_value_twd = gold_data['total_market_value_usd'] * exchange_rate
    
    grand_total_market_value_twd = total_stock_value_twd + cash_total_value_twd + total_crypto_value_twd + short_term_bonds_total_value_twd + long_term_bonds_total_value_twd + gold_total_value_twd
    
    grand_total_cost_twd = (us_total_cost * exchange_rate) + tw_total_cost + (short_term_bonds_data['total_cost_usd'] * exchange_rate) + (long_term_bonds_data['total_cost_usd'] * exchange_rate) + cash_total_value_twd + (crypto_data['total_cost_usd'] * exchange_rate) + (gold_data['total_cost_usd'] * exchange_rate)
    
    grand_total_profit_twd = grand_total_market_value_twd - grand_total_cost_twd
    grand_total_profit_pct = (grand_total_profit_twd / grand_total_cost_twd * 100) if grand_total_cost_twd else 0.0
    
    # ---- 組合樣板參數 ----
    template_args = {
        'updated_at': updated_at_tw, 'exchange_rate': exchange_rate, 'hide_etf': hide_etf, 'excluded_join': "、".join(sorted(EXCLUDED_ETFS_US)),
        'us_table': us_table, 'us_total_market_value': us_total_market_value, 'us_total_cost': us_total_cost, 'us_total_profit': us_total_profit, 'us_total_profit_pct': us_total_profit_pct,
        'us_core_total_market_value': us_core_total_market_value, 'us_core_total_cost': us_core_total_cost, 'us_core_total_profit': us_core_total_profit, 'us_core_total_profit_pct': us_core_total_profit_pct,
        'tw_table': tw_table, 'tw_total_market_value': tw_total_market_value, 'tw_total_cost': tw_total_cost, 'tw_total_profit': tw_total_profit, 'tw_total_profit_pct': tw_total_profit_pct,
        'cash_table': cash_table, 'cash_total_value_twd': cash_total_value_twd,
        'total_stock_value_twd': total_stock_value_twd, 
        'total_crypto_value_twd': total_crypto_value_twd, 
        'short_term_bonds_total_value_twd': short_term_bonds_total_value_twd, 
        'long_term_bonds_total_value_twd': long_term_bonds_total_value_twd,
        'gold_total_value_twd': gold_total_value_twd,
        'grand_total_market_value_twd': grand_total_market_value_twd, 'grand_total_cost_twd': grand_total_cost_twd, 'grand_total_profit_twd': grand_total_profit_twd, 'grand_total_profit_pct': grand_total_profit_pct,

        # 新增：四大類（USD）
        'power_total_usd': power_total_usd,
        'index_total_usd': index_total_usd,
        'defense_total_usd': defense_total_usd,
        'tech_other_total_usd': tech_other_total_usd,
    }

    # 使用清晰的前綴來合併字典
    for prefix, data_dict in [('short_term_bonds', short_term_bonds_data), ('long_term_bonds', long_term_bonds_data), ('crypto', crypto_data), ('gold', gold_data)]:
        for key, value in data_dict.items():
            template_args[f'{prefix}_{key}'] = value

    return render_template_string(TEMPLATE, **template_args)


@app.get("/health")
def health():
    return {"status": "ok"}

# 本機執行（Render 用 gunicorn，不會跑到這裡）
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
