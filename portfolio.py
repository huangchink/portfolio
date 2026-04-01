# -*- coding: utf-8 -*-
"""
Usage:
  pip install -r requirements.txt
  python portfolio.py --serve
  python portfolio.py --output docs/index.html

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
EXCLUDED_ETFS_US = set()

FULL_PORTFOLIO = [
    {"symbol": "TSM",   "shares": 65,        "cost": 311.863846},
    {"symbol": "SNPS",  "shares": 4,         "cost": 397.15},
    {"symbol": "YUM",   "shares": 1,         "cost": 141.34},
    {"symbol": "UNH",   "shares": 22,        "cost": 310.86},
    {"symbol": "GOOGL", "shares": 80.47318,  "cost": 185.028},
    {"symbol": "NVDA",  "shares": 40.1387,   "cost": 133.039},
    {"symbol": "QCOM",  "shares": 12,        "cost": 161.4525},
    {"symbol": "MSFT",  "shares": 3,         "cost": 437.97},
    {"symbol": "MU",    "shares": 50,        "cost": 367.1426},
    {"symbol": "KO",    "shares": 83.47431,  "cost": 68.009},
    {"symbol": "AEP",   "shares": 15,        "cost": 105.216},
    {"symbol": "DUK",   "shares": 16,        "cost": 115.79375},
    {"symbol": "MCD",   "shares": 10,        "cost": 303.413},
    {"symbol": "CEG",   "shares": 22,        "cost": 323.954},
    {"symbol": "LEU",   "shares": 18,        "cost": 265.216},
    {"symbol": "AMZN",  "shares": 18,        "cost": 220.786667},
    {"symbol": "ETN",   "shares": 2,         "cost": 341.46},
    {"symbol": "HUBB",  "shares": 4,         "cost": 413.425},
    {"symbol": "FSLR",  "shares": 5,         "cost": 246.698},
    {"symbol": "VST",   "shares": 14,        "cost": 166.08},
    {"symbol": "TSLA",  "shares": 5.51725,   "cost": 436.234},
]

# ================== 快取設定 ==================
_TTL_FAST   = 60
_TTL_NORMAL = 300
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
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1d"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            result = data.get('chart', {}).get('result')
            if result:
                meta = result[0].get('meta', {})
                price = meta.get('regularMarketPrice') or meta.get('chartPreviousClose')
                return float(price) if price is not None else None
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
    return None

def cached_close(symbol, ttl=_TTL_FAST):
    key = ("price", symbol)
    entry = _get_cache(key)
    now = _now()
    if entry and (now - entry["ts"] < ttl) and entry["price"] is not None:
        return entry["price"]
    price = fetch_price_from_yahoo(symbol)
    if price is not None:
        _set_cache(key, {"ts": now, "price": price})
        return price
    elif entry and entry["price"] is not None:
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
            mv = profit = profit_pct = 0.0
            price_str = mv_str = profit_pct_str = "N/A"
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

    top_10 = core_items[:10]
    chart_labels = [item['symbol'] for item in top_10]
    chart_data = [round(item['market_value'], 2) for item in top_10]

    others_mv = sum(item['market_value'] for item in core_items[10:])
    if others_mv > 0:
        chart_labels.append('Others')
        chart_data.append(round(others_mv, 2))

    # Day-of-year index for daily quote rotation
    day_of_year = datetime.now(timezone("Asia/Taipei")).timetuple().tm_yday

    return {
        "updated_at_tw": updated_at_tw,
        "core_items": core_items,
        "core_total_mv": core_total_mv,
        "core_total_cost": core_total_cost,
        "core_total_profit": core_total_profit,
        "core_total_pct": core_total_pct,
        "chart_labels": json.dumps(chart_labels),
        "chart_data": json.dumps(chart_data),
        "day_of_year": day_of_year,
    }


# ================== HTML 模板 ==================
TEMPLATE = r"""<!doctype html>
<html lang="zh-TW">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chink 的投資觀察清單</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,600;0,700;1,600&family=Source+Code+Pro:wght@400;600&family=Noto+Sans+TC:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --gold:       #c9a84c;
            --gold-light: #e8c97a;
            --gold-dim:   #7a5e22;
            --bg:         #0a0a0a;
            --surface:    #111111;
            --surface2:   #181818;
            --surface3:   #222222;
            --border:     #2a2a2a;
            --text:       #d4d4d4;
            --text-dim:   #6b6b6b;
            --green:      #3ddc84;
            --red:        #ff5f5f;
            --green-dim:  rgba(61,220,132,.12);
            --red-dim:    rgba(255,95,95,.12);
        }

        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: 'Noto Sans TC', sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            padding: 0 0 60px;
            /* subtle grain */
            background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
        }

        /* ── HEADER ── */
        header {
            position: relative;
            padding: 48px 40px 36px;
            max-width: 1100px;
            margin: 0 auto;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 24px;
        }
        header::after {
            content: '';
            position: absolute;
            bottom: -1px; left: 40px;
            width: 80px; height: 2px;
            background: linear-gradient(90deg, var(--gold), transparent);
        }

        .site-title {
            font-family: 'Playfair Display', serif;
            font-size: clamp(1.6rem, 4vw, 2.4rem);
            font-weight: 700;
            color: #fff;
            letter-spacing: -.5px;
            line-height: 1.1;
        }
        .site-title span {
            color: var(--gold);
        }
        .site-subtitle {
            font-size: .75rem;
            color: var(--text-dim);
            letter-spacing: 2px;
            text-transform: uppercase;
            margin-top: 6px;
        }
        .meta-time {
            font-family: 'Source Code Pro', monospace;
            font-size: .72rem;
            color: var(--text-dim);
            text-align: right;
            white-space: nowrap;
        }
        .meta-time strong { color: var(--gold-dim); display: block; font-size: .6rem; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 2px; }

        /* ── BUFFETT QUOTE BANNER ── */
        .quote-banner {
            max-width: 1100px;
            margin: 32px auto 0;
            padding: 0 40px;
        }
        .quote-card {
            position: relative;
            background: linear-gradient(135deg, #13100a 0%, #1a1408 50%, #13100a 100%);
            border: 1px solid var(--gold-dim);
            border-radius: 4px;
            padding: 28px 36px 28px 60px;
            overflow: hidden;
        }
        .quote-card::before {
            content: '\201C';
            font-family: 'Playfair Display', serif;
            font-size: 8rem;
            color: var(--gold-dim);
            position: absolute;
            top: -20px; left: 16px;
            line-height: 1;
            opacity: .5;
        }
        .quote-card::after {
            content: '';
            position: absolute;
            top: 0; left: 0;
            width: 3px; height: 100%;
            background: linear-gradient(180deg, var(--gold), var(--gold-dim));
        }
        .quote-text {
            font-family: 'Playfair Display', serif;
            font-style: italic;
            font-size: clamp(.95rem, 2vw, 1.15rem);
            color: #e8d9b0;
            line-height: 1.8;
            position: relative;
        }
        .quote-author {
            margin-top: 12px;
            font-size: .7rem;
            letter-spacing: 2px;
            text-transform: uppercase;
            color: var(--gold);
            font-weight: 500;
        }

        /* ── MAIN LAYOUT ── */
        .main {
            max-width: 1100px;
            margin: 32px auto 0;
            padding: 0 40px;
            display: grid;
            grid-template-columns: 320px 1fr;
            gap: 24px;
        }

        /* ── SUMMARY CARD ── */
        .summary-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 4px;
            padding: 28px;
            display: flex;
            flex-direction: column;
            gap: 0;
            height: fit-content;
        }
        .summary-label {
            font-size: .65rem;
            letter-spacing: 2px;
            text-transform: uppercase;
            color: var(--text-dim);
            margin-bottom: 20px;
            padding-bottom: 12px;
            border-bottom: 1px solid var(--border);
        }
        .stat-row {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            padding: 12px 0;
            border-bottom: 1px solid var(--border);
        }
        .stat-row:last-child { border-bottom: none; }
        .stat-name {
            font-size: .78rem;
            color: var(--text-dim);
            font-weight: 300;
        }
        .stat-value {
            font-family: 'Source Code Pro', monospace;
            font-size: .92rem;
            font-weight: 600;
            color: var(--text);
        }
        .stat-value.gain { color: var(--green); }
        .stat-value.loss { color: var(--red); }
        .stat-sub {
            font-size: .7rem;
            color: var(--text-dim);
            margin-top: 2px;
            font-family: 'Source Code Pro', monospace;
        }

        /* ── CHART ── */
        .chart-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 4px;
            padding: 28px;
        }
        .chart-label {
            font-size: .65rem;
            letter-spacing: 2px;
            text-transform: uppercase;
            color: var(--text-dim);
            margin-bottom: 20px;
            padding-bottom: 12px;
            border-bottom: 1px solid var(--border);
        }
        .chart-inner {
            position: relative;
            height: 260px;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        /* ── TABLE SECTION ── */
        .table-section {
            max-width: 1100px;
            margin: 24px auto 0;
            padding: 0 40px;
        }
        .table-header {
            font-size: .65rem;
            letter-spacing: 2px;
            text-transform: uppercase;
            color: var(--text-dim);
            padding: 0 0 12px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 2px;
        }
        .table-wrapper {
            overflow-x: auto;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            min-width: 620px;
        }
        thead tr {
            border-bottom: 1px solid var(--border);
        }
        th {
            font-size: .62rem;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            color: var(--text-dim);
            font-weight: 500;
            padding: 12px 16px;
            text-align: right;
            background: transparent;
        }
        th:first-child { text-align: left; }
        tbody tr {
            border-bottom: 1px solid #1a1a1a;
            transition: background .15s;
        }
        tbody tr:hover { background: var(--surface2); }
        td {
            padding: 13px 16px;
            font-size: .82rem;
            text-align: right;
            font-family: 'Source Code Pro', monospace;
            color: var(--text);
            border: none;
        }
        td:first-child {
            font-family: 'Noto Sans TC', sans-serif;
            font-weight: 700;
            font-size: .85rem;
            color: #fff;
            text-align: left;
            letter-spacing: .5px;
        }
        .gain-cell { color: var(--green); }
        .loss-cell { color: var(--red); }
        .gain-bg { background: var(--green-dim); border-radius: 3px; padding: 2px 6px; }
        .loss-bg { background: var(--red-dim); border-radius: 3px; padding: 2px 6px; }

        /* ── RANK BADGE ── */
        .rank {
            display: inline-block;
            width: 20px; height: 20px;
            line-height: 20px;
            text-align: center;
            font-size: .65rem;
            font-family: 'Source Code Pro', monospace;
            border-radius: 2px;
            background: var(--surface3);
            color: var(--text-dim);
            margin-right: 8px;
            vertical-align: middle;
        }
        .rank.top { background: var(--gold-dim); color: var(--gold); }

        /* ── FOOTER ── */
        footer {
            max-width: 1100px;
            margin: 48px auto 0;
            padding: 0 40px;
            font-size: .65rem;
            color: var(--text-dim);
            letter-spacing: .5px;
            border-top: 1px solid var(--border);
            padding-top: 20px;
        }

        /* ── RESPONSIVE ── */
        @media (max-width: 800px) {
            header { padding: 32px 20px 24px; flex-direction: column; align-items: flex-start; }
            header::after { left: 20px; }
            .quote-banner { padding: 0 20px; }
            .quote-card { padding: 22px 24px 22px 48px; }
            .main { padding: 0 20px; grid-template-columns: 1fr; }
            .table-section { padding: 0 20px; }
            footer { padding: 20px 20px 0; }
        }
    </style>
</head>
<body>

<!-- ── HEADER ── -->
<header>
    <div>
        <div class="site-title">Chink Portfolio</div>
        <div class="site-subtitle">Investment Watchlist · 自選股追蹤</div>
    </div>
    <div class="meta-time">
        <strong>Last Updated</strong>
        {{ updated_at_tw }} 台北時間
    </div>
</header>

<!-- ── BUFFETT QUOTE ── -->
{% set quotes = [
    '投資的第一條規則是永遠不要賠錢。第二條規則是永遠不要忘記第一條。',
    '價格是你所付出的，價值是你所得到的。',
    '如果找不到在睡覺時也能賺錢的方法，你將會工作一輩子到死。',
    '以合理的價格買下一家好公司，比用便宜的價格買下一家普通的公司好得多。',
    '別人恐懼我貪婪，別人貪婪我恐懼。',
    '如果你沒有持有一檔股票 10 年的想法，那連 10 分鐘都不要持有。',
    '只有當潮水退去時，才知道誰在裸泳。',
    '分散投資是無知的保護傘，對於那些知道自己在做什麼的人來說，這意義不大。',
    # '預測下雨沒有用，建造方舟才有用。',
    '不要投資於你不了解的事物。',
    '建立良好的聲譽需要 20 年，但要毀掉它只需要 5 分鐘。',
    '我們不必比別人聰明，我們只需要比別人更有紀律。',
    # '在困難時刻，贏家和輸家將表露無遺。',
    '最成功的交易是做自己喜歡的事。',
    '最好的投資就是投資自己。'
] %}
{% set today_quote = quotes[day_of_year % quotes|length] %}

<div class="quote-banner">
    <div class="quote-card">
        <div class="quote-text">{{ today_quote }}</div>
        <div class="quote-author">— Warren Buffett · 巴菲特語錄</div>
    </div>
</div>

<!-- ── DASHBOARD ── -->
<div class="main">
    <!-- Summary -->
    <div class="summary-card">
        <div class="summary-label">Portfolio Summary · 持倉總覽</div>

        <div class="stat-row">
            <div>
                <div class="stat-name">持股總市值</div>
            </div>
            <div style="text-align:right">
                <div class="stat-value">${{ '%.0f' % core_total_mv }}</div>
                <div class="stat-sub">USD</div>
            </div>
        </div>

        <div class="stat-row">
            <div>
                <div class="stat-name">持股總成本</div>
            </div>
            <div style="text-align:right">
                <div class="stat-value">${{ '%.0f' % core_total_cost }}</div>
                <div class="stat-sub">USD</div>
            </div>
        </div>

        <div class="stat-row">
            <div>
                <div class="stat-name">總報酬金額</div>
            </div>
            <div style="text-align:right">
                <div class="stat-value {% if core_total_pct > 0 %}gain{% elif core_total_pct < 0 %}loss{% endif %}">
                    {% if core_total_profit >= 0 %}+{% endif %}${{ '%.0f' % core_total_profit }}
                </div>
                <div class="stat-sub">USD</div>
            </div>
        </div>

        <div class="stat-row">
            <div>
                <div class="stat-name">總報酬率</div>
            </div>
            <div style="text-align:right">
                <div class="stat-value {% if core_total_pct > 0 %}gain{% elif core_total_pct < 0 %}loss{% endif %}">
                    {% if core_total_pct >= 0 %}+{% endif %}{{ '%.2f' % core_total_pct }}%
                </div>
            </div>
        </div>
    </div>

    <!-- Chart -->
    <div class="chart-card">
        <div class="chart-label">前十大持股佔比 · Top 10 Holdings</div>
        <div class="chart-inner">
            <canvas id="holdingsChart"></canvas>
        </div>
    </div>
</div>

<!-- ── TABLE ── -->
<div class="table-section">
    <div class="table-header">Holdings Detail · 個股明細</div>
    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>代號 Symbol</th>
                    <th>現價</th>
                    <th>成本</th>
                    <th>股數</th>
                    <th>市值 (USD)</th>
                    <th>報酬率</th>
                </tr>
            </thead>
            <tbody>
                {% for it in core_items %}
                <tr>
                    <td>
                        <span class="rank {% if loop.index <= 3 %}top{% endif %}">{{ loop.index }}</span>
                        {{ it.symbol }}
                    </td>
                    <td>{{ it.price_str }}</td>
                    <td>{{ it.cost_str }}</td>
                    <td>{{ it.shares_str }}</td>
                    <td>{{ it.mv_str }}</td>
                    <td>
                        <span class="{% if it.profit_pct > 0 %}gain-cell gain-bg{% elif it.profit_pct < 0 %}loss-cell loss-bg{% endif %}">
                            {% if it.profit_pct > 0 %}+{% endif %}{{ it.profit_pct_str }}
                        </span>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<footer>
    資料來源：Yahoo Finance · 僅供個人追蹤參考，不構成任何投資建議
</footer>

<script>
const ctx = document.getElementById('holdingsChart').getContext('2d');
const chartLabels = {{ chart_labels | safe }};
const chartData   = {{ chart_data   | safe }};

const GOLD_PALETTE = [
    '#4e9af1','#f16b4e','#4ecf8a','#b06cf7','#f7c24e',
    '#4ec8f7','#f74e8e','#7ecf4e','#f74e4e','#4e6ff7','#f7934e'
];

new Chart(ctx, {
    type: 'doughnut',
    data: {
        labels: chartLabels,
        datasets: [{
            data: chartData,
            backgroundColor: GOLD_PALETTE,
            borderColor: '#0a0a0a',
            borderWidth: 2,
            hoverOffset: 8
        }]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '62%',
        plugins: {
            legend: {
                position: 'right',
                labels: {
                    color: '#9a9a9a',
                    boxWidth: 10,
                    boxHeight: 10,
                    padding: 12,
                    font: { family: "'Source Code Pro', monospace", size: 11 }
                }
            },
            tooltip: {
                backgroundColor: '#1a1a1a',
                borderColor: '#2a2a2a',
                borderWidth: 1,
                titleColor: '#ffffff',
                bodyColor: '#c9a84c',
                callbacks: {
                    label: function(context) {
                        const value = context.parsed;
                        const total = context.dataset.data.reduce((a, b) => a + b, 0);
                        const pct   = ((value / total) * 100).toFixed(1);
                        const fmt   = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
                        return ` ${fmt.format(value)}  (${pct}%)`;
                    }
                }
            }
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
    with app.app_context():
        return render_template_string(TEMPLATE, **_build_portfolio_snapshot())

def main():
    parser = argparse.ArgumentParser(description="Portfolio watchlist server / static site generator")
    parser.add_argument("--output", help="Write a static HTML snapshot to this path")
    parser.add_argument("--serve", action="store_true", help="Run the Flask server")
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
        app.run(host="0.0.0.0", port=port, debug=True, use_reloader=True, reloader_type='stat')

if __name__ == "__main__":
    main()