# -*- coding: utf-8 -*-
"""
Usage:
  pip install -r requirements.txt
  python portfolio_chart.py --serve
  python portfolio_chart.py --output docs/index.html

Local preview: http://127.0.0.1:5000/
"""

from flask import Flask, render_template_string
from datetime import datetime
import requests
import json
import threading, time, os, logging, argparse
from pytz import timezone
from pathlib import Path

app = Flask(__name__)

# ================== 持股設定 ==================
# 如要排除特定 ETF，將代號放到這個集合
EXCLUDED_ETFS_US = set()

FULL_PORTFOLIO = [
    # ETF（若不想顯示就移到 EXCLUDED_ETFS_US）
    # {'symbol': 'SGOV',  'shares': 1100,  'cost': 100.40},
    # {'symbol': 'VOO',   'shares': 70.00, 'cost': 506.75},
    # {'symbol': 'VEA',   'shares': 86.80, 'cost': 53.55},
    # {'symbol': 'GLD',   'shares': 16.55, 'cost': 300.10},
    # {'symbol': 'TLT',   'shares': 224.7, 'cost': 92.22},
    # {'symbol': 'BOXX',  'shares': 100,   'cost': 110.71},
    # {'symbol': 'XLU',   'shares': 250, 'cost': 42.854},
    # {'symbol': 'EWT',   'shares': 100,   'cost': 61.27},
    # {'symbol': 'XLU',   'shares': 87.71, 'cost': 83.80},
    # {'symbol': 'VT',    'shares': 50,    'cost': 133.69},
    # {"symbol": "VOO", "shares": 70.00, "cost": 506.75},
    # {"symbol": "VEA", "shares": 86.80, "cost": 53.55},
    # {"symbol": "XLU", "shares": 250, "cost": 42.854},
    # {"symbol": "EWT", "shares": 100, "cost": 61.27},
    # {"symbol": "PYPL", "shares": 35, "cost": 68.855},
    {"symbol": "TSM", "shares": 65, "cost": 311.863846},
    {"symbol": "SNPS", "shares": 4, "cost": 397.15},
    {"symbol": "YUM", "shares": 1, "cost": 141.34},
    {"symbol": "UNH", "shares": 22, "cost": 310.86},
    {"symbol": "GOOGL", "shares": 80.47318, "cost": 185.028},
    {"symbol": "NVDA", "shares": 40.1387, "cost": 133.039},
    # {"symbol": "MSTR", "shares": 10, "cost": 287.304},
    {"symbol": "QCOM", "shares": 12, "cost": 161.4525},
    
    {"symbol": "MSFT", "shares": 3, "cost": 437.97},

    {"symbol": "MU", "shares": 50, "cost": 367.1426},


    {"symbol": "KO", "shares": 83.47431, "cost": 68.009},
    {"symbol": "AEP", "shares": 15, "cost": 105.216},
    {"symbol": "DUK", "shares": 16, "cost": 115.79375},
    {"symbol": "MCD", "shares": 10, "cost": 303.413},
    {"symbol": "CEG", "shares": 20, "cost": 328.856},
    {"symbol": "LEU", "shares": 18, "cost": 265.216},
    {"symbol": "AMZN", "shares": 18, "cost": 220.786667},
    {"symbol": "ETN", "shares": 2, "cost": 341.46},
    {"symbol": "HUBB", "shares": 4, "cost": 413.425},
    {"symbol": "FSLR", "shares": 5, "cost": 246.698},
    # {"symbol": "META", "shares": 12, "cost": 713.02},
    {"symbol": "VST", "shares": 14, "cost": 166.08},
    # {"symbol": "BABA", "shares": 2, "cost": 169.42},
    {"symbol": "EOSE", "shares": 54, "cost": 12.28963},
    {"symbol": "FCX", "shares": 5, "cost": 49.66},
    {"symbol": "SMR", "shares": 10, "cost": 19.55},
    {"symbol": "GIS", "shares": 2, "cost": 49.695},
    {"symbol": "INTC", "shares": 19, "cost": 37.003},
    {"symbol": "UUUU", "shares": 30, "cost": 16.96},
    {"symbol": "TSLA", "shares": 5.51725, "cost": 436.234},
    # {"symbol": "VWO", "shares": 60, "cost": 54.74},
]



# ================== 快取設定 ==================
_TTL_FAST   = 60        # 1 分鐘：即時刷新
_TTL_NORMAL = 300       # 5 分鐘：一般 TTL
_cache = {}
_cache_lock = threading.Lock()


def _now() -> float:
    return time.time()


def _get_cache(key):
    with _cache_lock:
        return _cache.get(key)


def _set_cache(key, value):
    with _cache_lock:
        _cache[key] = value

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def fetch_price_from_yahoo(symbol):
    """
    Directly fetch price from Yahoo Finance API to avoid yfinance library issues.
    """
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1d"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            result = data.get('chart', {}).get('result')
            if result:
                meta = result[0].get('meta', {})
                # Try to get regularMarketPrice, fallback to chartPreviousClose
                price = meta.get('regularMarketPrice') or meta.get('chartPreviousClose')
                return float(price) if price is not None else None
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
    return None

def cached_close(symbol, ttl=_TTL_FAST):
    """
    取得最近收盤價，優先抓快取，若無則抓 Yahoo API。
    """
    key = ("price", symbol)
    entry = _get_cache(key)
    now = _now()
    
    # Check cache based on TTL
    if entry and (now - entry["ts"] < ttl) and entry["price"] is not None:
        return entry["price"]
        
    # Fetch new data
    price = fetch_price_from_yahoo(symbol)
    
    # Update cache (even if failed, we might cache None to avoid hammering API, but here we retry next time)
    if price is not None:
        _set_cache(key, {"ts": now, "price": price})
        return price
    elif entry and entry["price"] is not None:
        # If fetch failed but we have old cache, return old cache even if expired
        return entry["price"]
        
    return "N/A"


def _build_core_rows():
    return [r for r in FULL_PORTFOLIO if r["symbol"] not in EXCLUDED_ETFS_US]


def _build_portfolio_snapshot():
    updated_at_tw = datetime.now(timezone("Asia/Taipei")).strftime("%Y-%m-%d %H:%M")
    core_rows = _build_core_rows()

    core_items = []
    core_total_mv = 0.0
    for row in core_rows:
        price = cached_close(row["symbol"], ttl=_TTL_FAST)
        if price == "N/A":
            mv = 0.0
            profit = 0.0
            profit_pct = 0.0
            price_str = "N/A"
            mv_str = "N/A"
            profit_pct_str = "N/A"
        else:
            mv = price * row["shares"]
            profit = mv - row["cost"] * row["shares"]
            profit_pct = (profit / (row["cost"] * row["shares"]) * 100) if row["cost"] * row["shares"] else 0.0
            price_str = f"{price:.2f}"
            mv_str = f"{mv:.2f}"
            profit_pct_str = f"{profit_pct:.2f}%"

        core_total_mv += mv
        core_items.append({
            "symbol": row["symbol"],
            "price": price,
            "price_str": price_str,
            "shares": row["shares"],
            "shares_str": f"{row['shares']:.2f}",
            "cost": row["cost"],
            "cost_str": f"{row['cost']:.2f}",
            "market_value": mv,
            "mv_str": mv_str,
            "profit": profit,
            "profit_pct": profit_pct,
            "profit_pct_str": profit_pct_str,
        })

    core_total_cost = sum(r["cost"] * r["shares"] for r in core_rows)
    core_total_profit = sum(it["profit"] for it in core_items)
    core_total_pct = (core_total_profit / core_total_cost * 100) if core_total_cost else 0.0

    core_items.sort(key=lambda x: x["market_value"], reverse=True)
    
    # 準備圖表數據 - 前十大持股
    top_10 = core_items[:10]
    chart_labels = [item['symbol'] for item in top_10]
    chart_data = [round(item['market_value'], 2) for item in top_10]
    
    # 計算其他
    others_mv = sum(item['market_value'] for item in core_items[10:])
    if others_mv > 0:
        chart_labels.append('Others')
        chart_data.append(round(others_mv, 2))

    return {
        "updated_at_tw": updated_at_tw,
        "core_items": core_items,
        "core_total_mv": core_total_mv,
        "core_total_cost": core_total_cost,
        "core_total_profit": core_total_profit,
        "core_total_pct": core_total_pct,
        "chart_labels": json.dumps(chart_labels),
        "chart_data": json.dumps(chart_data),
    }


# ================== HTML 模板 ==================
TEMPLATE = r"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chink 的投資觀察清單</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --primary-color: #e0e0e0;
            --accent-color: #3498db;
            --success-color: #4caf50;
            --danger-color: #f44336;
            --bg-color: #121212;
            --card-bg: #1e1e1e;
            --text-color: #e0e0e0;
            --border-color: #333333;
        }
        
        body { 
            font-family: "微軟正黑體", sans-serif; 
            background: var(--bg-color); 
            color: var(--text-color);
            margin: 0;
            padding: 20px;
        }
        
        .container { 
            max-width: 1000px; 
            margin: 32px auto; 
            background: var(--card-bg); 
            padding: 28px; 
            border-radius: 12px; 
            box-shadow: 0 2px 10px rgba(0,0,0,.06); 
        }
        
        h1 { 
            margin: 0 0 8px; 
            color: var(--primary-color);
        }
        
        .meta { 
            color: #6c757d; 
            margin-bottom: 16px; 
        }
        
        .dashboard-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .summary-card {
            background:#2c2c2c; 
            padding:18px; 
            border-radius:10px;
            height: fit-content;
        }

        .summary-row { 
            display: flex; 
            justify-content: space-between; 
            margin: 6px 0;
        }
        
        .chart-container {
            position: relative;
            height: 250px;
            width: 100%;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        
        table { 
            width:100%; 
            border-collapse: collapse; 
            margin-top: 14px; 
        }
        
        th, td { 
            border: 1px solid var(--border-color); 
            padding: 10px 12px; 
            text-align: left; 
        }
        
        th { 
            background: #2c2c2c; 
            color: #e0e0e0;
        }
        
        .right { text-align:right; }
        .gain { color: var(--success-color); font-weight:700; }
        .loss { color: var(--danger-color); font-weight:700; }
        
        @media (max-width: 768px) {
            .dashboard-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
<div class="container">
    <h1>Chink 自選股</h1>
    <div class="meta">最後更新：{{ updated_at_tw }}（台北時間）</div>

    <div class="dashboard-grid">
        <!-- Summary Section -->
        <div class="summary-card">
            <div class="summary-row">
                <span>持股總市值</span>
                <span class="right"><b>{{ '%.2f' % core_total_mv }}</b> USD</span>
            </div>
            <div class="summary-row">
                <span>持股總成本</span>
                <span class="right"><b>{{ '%.2f' % core_total_cost }}</b> USD</span>
            </div>
            <div class="summary-row">
                <span>持股總報酬</span>
                <span class="right {% if core_total_pct > 0 %}gain{% elif core_total_pct < 0 %}loss{% endif %}">
                    <b>{{ '%.2f' % core_total_profit }}</b> USD（{{ '%.2f' % core_total_pct }}%）
                </span>
            </div>
        </div>
        
        <!-- Chart Section -->
        <div class="chart-container">
            <canvas id="holdingsChart"></canvas>
        </div>
    </div>

    <!-- Original Table Style -->
    <table>
        <tr>
            <th>代號</th>
            <th class="right">現價</th>
            <th class="right">成本</th>
            <th class="right">股數</th>
            <th class="right">市值</th>
            <th class="right">個股報酬</th>
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

<script>
    const ctx = document.getElementById('holdingsChart').getContext('2d');
    const chartLabels = {{ chart_labels | safe }};
    const chartData = {{ chart_data | safe }};
    
    // Generate distinct colors
    const backgroundColors = [
        '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', 
        '#FF9F40', '#E7E9ED', '#76D7C4', '#F7DC6F', '#85C1E9', '#D2B4DE'
    ];

    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: chartLabels,
            datasets: [{
                data: chartData,
                backgroundColor: backgroundColors,
                borderWidth: 1,
                hoverOffset: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        color: '#e0e0e0',
                        boxWidth: 12,
                        font: {
                            family: '"微軟正黑體", sans-serif',
                            size: 11
                        }
                    }
                },
                title: {
                    display: true,
                    text: '前十大持股佔比',
                    color: '#e0e0e0',
                    font: {
                        family: '"微軟正黑體", sans-serif',
                        size: 14,
                        weight: '600'
                    },
                    padding: {
                        bottom: 10
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let label = context.label || '';
                            if (label) {
                                label += ': ';
                            }
                            const value = context.parsed;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = ((value / total) * 100).toFixed(1) + '%';
                            if (context.parsed !== null) {
                                label += new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value);
                            }
                            return label + ' (' + percentage + ')';
                        }
                    }
                }
            },
            layout: {
                padding: 5
            }
        }
    });
</script>
</body>
</html>
"""


# ================== 路由 ==================
@app.route("/")
def watchlist_only():
    return render_template_string(TEMPLATE, **_build_portfolio_snapshot())


@app.get("/health")
def health():
    return {"status": "ok"}


def render_portfolio_html():
    """Return rendered HTML (used for static export)."""
    with app.app_context():
        return render_template_string(TEMPLATE, **_build_portfolio_snapshot())


def main():
    parser = argparse.ArgumentParser(description="Portfolio watchlist server / static site generator")
    parser.add_argument(
        "--output",
        help="Write a static HTML snapshot to this path (ex: docs/index.html for GitHub Pages)",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Run the Flask server after generating the static HTML",
    )
    args = parser.parse_args()

    if args.output:
        html = render_portfolio_html()
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        print(f"Wrote portfolio page to {output_path}")
        if not args.serve:
            return

    if args.serve or not args.output:
        port = int(os.environ.get("PORT", 5000))
        # use_reloader=True, reloader_type='stat' to avoid watchdog issues
        app.run(host="0.0.0.0", port=port, debug=True, use_reloader=True, reloader_type='stat')


if __name__ == "__main__":
    main()
