# -*- coding: utf-8 -*-
"""
本機：
  pip install flask yfinance
  python portfolio.py
開啟：http://127.0.0.1:5000/

Render（建議 Start Command）：
  gunicorn portfolio:app --bind 0.0.0.0:$PORT --access-logfile - --error-logfile - --timeout 120 --forwarded-allow-ips='*'
"""

from flask import Flask, render_template_string
from datetime import datetime
from werkzeug.middleware.proxy_fix import ProxyFix
import yfinance as yf
import pandas as pd
import threading, time, os, logging
from pytz import timezone

app = Flask(__name__)
# 代理相容（在 Render 這類代理後正確判定 https/host）
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# 降噪：隱藏 yfinance 的「possibly delisted」等訊息
logging.getLogger("yfinance").setLevel(logging.ERROR)

# ================== 自選股設定 ==================
# 說明：
# 1) 下方 FULL_PORTFOLIO = 你的全部持倉（含 ETF）
# 2) EXCLUDED_ETFS_US = 要排除的 ETF 清單
# 3) 頁面只會顯示「自選股」＝ FULL_PORTFOLIO 扣掉 EXCLUDED_ETFS_US 的項目
EXCLUDED_ETFS_US = {'SGOV', 'VOO', 'VEA', 'TLT', 'BOXX', 'GLD', 'VT', 'EWT', 'XLU'}

FULL_PORTFOLIO = [
    # ETF（會被排除）
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
    # {'symbol': 'COST',   'shares': 2,     'cost': 920.255},
    {'symbol': 'ETN',   'shares': 1,     'cost': 335.04},
    {'symbol': 'HUBB',   'shares': 4,     'cost': 413.425},
    {'symbol': 'META',   'shares': 12,     'cost': 713.02},
    # {'symbol': 'MU',   'shares': 8,     'cost': 168.81125},
    # {'symbol': 'VST',   'shares': 4,     'cost': 204.68},
    # {'symbol': 'BABA',   'shares': 2,     'cost': 169.42},
    {'symbol': 'EOSE',   'shares':11,     'cost': 13.331},
    {'symbol': 'FCX',   'shares': 3,     'cost': 41.6133},
    {'symbol': 'SMR',   'shares':10,     'cost': 19.55},

    # {'symbol': 'GIS',   'shares': 2,     'cost': 49.695},
    # {'symbol': 'IDMO',   'shares': 60,     'cost': 53.48},

    {'symbol': 'INTC',   'shares': 19,     'cost': 37.003},
    {'symbol': 'UUUU',   'shares': 30,     'cost': 16.96},

    {'symbol': 'TSLA',   'shares': 1.473,     'cost': 423.885},
    # {'symbol': 'VWO',   'shares': 60,     'cost': 54.74},

    # {'symbol': 'AVDV',   'shares': 40,     'cost':87.945},

]




# ================== 輕量 TTL 快取 ==================
_TTL_FAST   = 60        # 1 分鐘：即時/當日
_TTL_NORMAL = 300       # 5 分鐘：一般
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
    避免假日／停牌導致 period='1d' 為空而報「possibly delisted」。
    """
    for period, t in (("7d", ttl), ("1mo", max(ttl, _TTL_NORMAL))):
        df = cached_history(symbol, period=period, ttl=t)
        if not df.empty and "Close" in df:
            close = df["Close"].dropna()
            if not close.empty:
                return float(close.iloc[-1])
    return 'N/A'

# ================== HTML 模板（僅自選股） ==================
TEMPLATE = r"""
<html>
<head>
    <meta charset="utf-8">
    <title>Chink's Watchlist</title>
    <style>
        body { font-family: "微軟正黑體", Arial, sans-serif; background: #f4f6f8; }
        .container { max-width: 1000px; margin: 32px auto; background: #fff; padding: 28px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,.06); }
        h1 { margin: 0 0 8px; color: #2c3e50; }
        .meta { color: #6c757d; margin-bottom: 16px; }
        .summary { background:#f8f9fa; padding:18px; border-radius:10px; margin:18px 0; }
        .summary-row { display:flex; justify-content:space-between; margin:6px 0; }
        table { width:100%; border-collapse: collapse; margin-top: 14px; }
        th, td { border: 1px solid #eaecef; padding: 10px 12px; text-align: left; }
        th { background: #f0f3f6; }
        .right { text-align:right; }
        .gain { color:#c62828; font-weight:700; }   /* 紅漲 */
        .loss { color:#2e7d32; font-weight:700; }   /* 綠跌 */
    </style>
</head>
<body>
<div class="container">
    <h1>Chink's 自選股績效</h1>
    <div class="meta">更新時間：{{ updated_at_tw }}（台灣） </div>

    <div class="summary">
        <div class="summary-row">
            <span>自選股總市值：</span>
            <span class="right"><b>{{ '%.2f' % core_total_mv }}</b> USD</span>
        </div>
        <div class="summary-row">
            <span>自選股總成本：</span>
            <span class="right"><b>{{ '%.2f' % core_total_cost }}</b> USD</span>
        </div>
        <div class="summary-row">
            <span>自選股總報酬：</span>
            <span class="right {% if core_total_pct > 0 %}gain{% elif core_total_pct < 0 %}loss{% endif %}">
                <b>{{ '%.2f' % core_total_profit }}</b> USD（{{ '%.2f' % core_total_pct }}%）
            </span>
        </div>
    </div>

    <table>
        <tr>
            <th>代碼</th>
            <th class="right">現價</th>
            <th class="right">成本價</th>
            <th class="right">持有股數</th>
            <th class="right">市值</th>
            <th class="right">個別報酬率</th>
        </tr>
        {% for it in core_items %}
        <tr>
            <td>{{ it.symbol }}</td>
            <td class="right">{{ it.price_str }}</td>
            <td class="right">{{ it.cost_str }}</td>
            <td class="right">{{ it.shares_str }}</td>
            <td class="right">{{ it.mv_str }}</td>
            <td class="right {% if it.profit_pct > 0 %}gain{% elif it.profit_pct < 0 %}loss{% endif %}">{{ it.profit_pct_str }}</td>
        </tr>
        {% endfor %}
    </table>
</div>
</body>
</html>
"""

# ================== 路由 ==================
@app.route("/")
def watchlist_only():
    updated_at_tw = datetime.now(timezone('Asia/Taipei')).strftime("%Y-%m-%d %H:%M")

    # 濾出自選股（排 ETF）
    core_rows = [r for r in FULL_PORTFOLIO if r['symbol'] not in EXCLUDED_ETFS_US]

    core_items = []
    core_total_mv = 0.0
    for row in core_rows:
        price = cached_close(row['symbol'], ttl=_TTL_FAST)
        if price == 'N/A':
            mv = 0.0
            profit = 0.0
            profit_pct = 0.0
            price_str = 'N/A'
            mv_str = 'N/A'
            profit_pct_str = 'N/A'
        else:
            mv = price * row['shares']
            profit = mv - row['cost'] * row['shares']
            profit_pct = (profit / (row['cost'] * row['shares']) * 100) if row['cost'] * row['shares'] else 0.0
            price_str = f"{price:.2f}"
            mv_str = f"{mv:.2f}"
            profit_pct_str = f"{profit_pct:.2f}%"

        core_total_mv += mv
        core_items.append({
            "symbol": row['symbol'],
            "price": price,
            "price_str": price_str,
            "shares": row['shares'],
            "shares_str": f"{row['shares']:.2f}",
            "cost": row['cost'],
            "cost_str": f"{row['cost']:.2f}",
            "market_value": mv,
            "mv_str": mv_str,
            "profit": profit,
            "profit_pct": profit_pct,
            "profit_pct_str": profit_pct_str,
        })

    core_total_cost = sum(r['cost'] * r['shares'] for r in core_rows)
    core_total_profit = sum(it["profit"] for it in core_items)
    core_total_pct = (core_total_profit / core_total_cost * 100) if core_total_cost else 0.0

    # 排序（市值大到小）
    core_items.sort(key=lambda x: x["market_value"], reverse=True)

    return render_template_string(
        TEMPLATE,
        updated_at_tw=updated_at_tw,

        core_items=core_items,
        core_total_mv=core_total_mv,
        core_total_cost=core_total_cost,
        core_total_profit=core_total_profit,
        core_total_pct=core_total_pct,
    )

@app.get("/health")
def health():
    return {"status": "ok"}

# 本機執行（Render 用 gunicorn，不會跑到這裡）
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
