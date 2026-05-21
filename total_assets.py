# -*- coding: utf-8 -*-
"""
Usage:
  pip install -r requirements.txt
  python total_assets.py --serve
  
Local preview: http://127.0.0.1:5001/
"""

from flask import Flask, render_template_string
from datetime import datetime
from pytz import timezone
import requests
import threading
import time
import argparse
import yfinance as yf

app = Flask(__name__)

# ================== 資產設定 ==================

# 1. 美股個股與ETF (包含黃金、美債)
US_STOCKS = [
    {"symbol": "TSM",   "shares": 81,        "cost": 368.334},
    {"symbol": "SNPS",  "shares": 1,         "cost": 459.31},
    {"symbol": "YUM",   "shares": 1,         "cost": 141.34},
    {"symbol": "UNH",   "shares": 15,        "cost": 310.86},
    {"symbol": "GOOGL", "shares": 80.47318,  "cost": 185.028},
    {"symbol": "GEV", "shares": 1,  "cost": 997.44},
    {"symbol": "INTC", "shares": 30,  "cost": 114.246},

    {"symbol": "NVDA",  "shares": 48.22095,   "cost": 140.098},
    {"symbol": "MU",    "shares": 6,        "cost": 418.088},
    {"symbol": "KO",    "shares": 85.47431,  "cost": 68.17},
    {"symbol": "AEP",   "shares": 15,        "cost": 105.216},
    {"symbol": "DUK",   "shares": 16,        "cost": 115.79375},
    {"symbol": "DPZ",   "shares": 3,        "cost": 368.993},
    {"symbol": "AXP",   "shares": 5,        "cost": 300.21},
    {"symbol": "V",   "shares": 5,        "cost": 310.006},
    {"symbol": "MCD",   "shares": 23,        "cost": 289.804783},
    {"symbol": "CEG",   "shares": 24,        "cost": 320.49375},
    {"symbol": "LEU",   "shares": 18,        "cost": 265.216},
    {"symbol": "AMZN",  "shares": 18,        "cost": 220.786667},
    {"symbol": "ETN",   "shares": 2,         "cost": 341.46},
    {"symbol": "HUBB",  "shares": 6,         "cost": 437.18},
    {"symbol": "FSLR",  "shares": 10,         "cost": 221.928},
    
    # ETF 等標的
    {"symbol": "AVDV", "shares": 30,         "cost": 99.17},
    # {"symbol": "EFV",  "shares": 40,         "cost": 78.925},
    {"symbol": "VOO",  "shares": 77.06978,   "cost": 517.407991},
    {"symbol": "VEA",  "shares": 108.98114,   "cost": 55.504191},

    {"symbol": "VPL",  "shares": 200,        "cost": 98.76775},
    {"symbol": "VT",   "shares": 30,         "cost": 139.225},
    {"symbol": "VWO",  "shares": 63.64034,   "cost": 54.753007},
    {"symbol": "XLU",  "shares": 371.52109,  "cost": 43.708367},
]

# 2. 台股
TW_STOCKS = [
    {"symbol": "006208.TW", "name": "富邦台50", "shares": 10000, "cost": 115.46},
    {"symbol": "0050.TW",   "name": "元大台灣50", "shares": 13609, "cost": 47.03},
    {"symbol": "2330.TW",   "name": "台積電", "shares": 1000,   "cost": 1686.29},
    {"symbol": "2454.TW",   "name": "聯發科", "shares": 50,    "cost": 1481},
    {"symbol": "2887.TW",   "name": "台新金", "shares": 5308,  "cost": 19.07},
    {"symbol": "2834.TW",   "name": "臺企銀", "shares": 3471,  "cost": 14.08},
    {"symbol": "2357.TW",   "name": "華碩", "shares": 120,   "cost": 576.58},
    {"symbol": "00713.TW",  "name": "元大台灣高息低波", "shares": 11427, "cost": 54.07},
]

# 3. 美債
US_BONDS = [
    {"symbol": "SGOV", "shares": 700, "cost": 100.413371},
]

# 4. 貴金屬
PRECIOUS_METALS = [
    {"symbol": "GLD", "shares": 21.36049, "cost": 321.523523},
]

# 5. 原物料
COMMODITIES = [
    {"symbol": "PDBC", "shares": 200, "cost": 17.575},
]

# 6. 儲蓄險
INSURANCE = [
    {"name": "添美盛美元", "value": 90417, "rate": 3.75, "currency": "USD"},
    {"name": "祿美滿利變美元", "value": 57963, "rate": 1.8, "currency": "USD"},
    {"name": "富貴年年終身壽險", "value": 312655, "rate": 7, "currency": "TWD"},
    {"name": "得意還本終身壽險", "value": 320257, "rate": 7, "currency": "TWD"},
    {"name": "鍾愛還本終身壽險", "value": 571998, "rate": 6.75, "currency": "TWD"},
    {"name": "富貴年年終身壽險", "value": 630487, "rate": 7, "currency": "TWD"},
    {"name": "好事年年終身壽險", "value": 2048616 - 800000, "rate": 2.25, "currency": "TWD"},
]

# 7. 加密貨幣
CRYPTO = [
    {"symbol": "BTC-USD", "shares": 0.02995415,  "cost": 110046.57},
    {"symbol": "ETH-USD", "shares": 0.003,  "cost": 0},
]

# 8. 銀行活存、定存、美金活存
BANK_DEPOSITS = [
    {"bank": "國泰世華",     "type": "台幣活存", "currency": "TWD", "amount": 670000},
    {"bank": "國泰世華",     "type": "美元活存", "currency": "USD", "amount": 20000},
]

# ================== 快取設定 ==================
_TTL_FAST   = 60
_cache = {}
_cache_lock = threading.Lock()

def _now() -> float:
    return time.time()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
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
    with _cache_lock:
        entry = _cache.get(key)
        now = _now()
        if entry and (now - entry["ts"] < ttl) and entry["price"] is not None:
            return entry["price"]
    price = fetch_price_from_yahoo(symbol)
    if price is None and symbol.endswith('.TW'):
        # Fallback for TW stocks
        try:
             ticker = yf.Ticker(symbol)
             price = ticker.fast_info['lastPrice']
        except:
             pass
    with _cache_lock:
        if price is not None:
            _cache[key] = {"ts": _now(), "price": price}
            return price
        elif entry and entry["price"] is not None:
            return entry["price"]
    return None

def get_usd_twd_rate():
    key = ("usd_twd_rate",)
    with _cache_lock:
        entry = _cache.get(key)
        now = _now()
        if entry and (now - entry["ts"] < 3600):
            return entry["rate"]
    rate = fetch_price_from_yahoo("TWD=X")
    if rate is None:
        rate = 32.5  # fallback
    with _cache_lock:
        _cache[key] = {"ts": _now(), "rate": rate}
    return rate

def _build_assets_snapshot():
    usd_twd = get_usd_twd_rate()

    # 1. US Stocks
    us_items = []
    us_total_cost_usd = 0.0
    us_total_mv_usd = 0.0
    for row in US_STOCKS:
        price = cached_close(row["symbol"])
        cost = row["cost"]
        shares = row["shares"]
        
        if price is None:
            price = cost # fallback to cost if API fails
            
        mv_usd = price * shares
        cost_usd = cost * shares
        profit_usd = mv_usd - cost_usd
        profit_pct = (profit_usd / cost_usd * 100) if cost_usd else 0
        
        us_total_cost_usd += cost_usd
        us_total_mv_usd += mv_usd
        
        us_items.append({
            "symbol": row["symbol"],
            "shares": shares,
            "cost_usd": cost,
            "price_usd": price,
            "mv_usd": mv_usd,
            "profit_pct": profit_pct
        })
    us_total_mv_twd = us_total_mv_usd * usd_twd
    us_total_cost_twd = us_total_cost_usd * usd_twd
    us_unrealized_twd = us_total_mv_twd - us_total_cost_twd
    us_return_pct = (us_unrealized_twd / us_total_cost_twd * 100) if us_total_cost_twd else 0

    # 2. TW Stocks
    tw_items = []
    tw_total_cost_twd = 0.0
    tw_total_mv_twd = 0.0
    for row in TW_STOCKS:
        price = cached_close(row["symbol"])
        cost = row["cost"]
        shares = row["shares"]
        
        if price is None:
            price = cost
            
        mv_twd = price * shares
        cost_twd = cost * shares
        profit_twd = mv_twd - cost_twd
        profit_pct = (profit_twd / cost_twd * 100) if cost_twd else 0
        
        tw_total_cost_twd += cost_twd
        tw_total_mv_twd += mv_twd
        
        tw_items.append({
            "name": row.get("name", ""),
            "symbol": row["symbol"].replace('.TW', ''),
            "shares": shares,
            "cost_twd": cost,
            "price_twd": price,
            "mv_twd": mv_twd,
            "profit_pct": profit_pct
        })
    tw_unrealized_twd = tw_total_mv_twd - tw_total_cost_twd
    tw_return_pct = (tw_unrealized_twd / tw_total_cost_twd * 100) if tw_total_cost_twd else 0

    # 3. Crypto
    crypto_items = []
    crypto_total_cost_usd = 0.0
    crypto_total_mv_usd = 0.0
    for row in CRYPTO:
        price = cached_close(row["symbol"])
        cost = row["cost"]
        shares = row["shares"]
        
        if price is None:
            price = cost
            
        mv_usd = price * shares
        cost_usd = cost * shares
        profit_usd = mv_usd - cost_usd
        profit_pct = (profit_usd / cost_usd * 100) if cost_usd else 0
        
        crypto_total_cost_usd += cost_usd
        crypto_total_mv_usd += mv_usd
        
        crypto_items.append({
            "symbol": row["symbol"].replace('-USD', ''),
            "shares": shares,
            "cost_usd": cost,
            "price_usd": price,
            "mv_usd": mv_usd,
            "profit_pct": profit_pct
        })
    crypto_total_mv_twd = crypto_total_mv_usd * usd_twd
    crypto_total_cost_twd = crypto_total_cost_usd * usd_twd
    crypto_unrealized_twd = crypto_total_mv_twd - crypto_total_cost_twd
    crypto_return_pct = (crypto_unrealized_twd / crypto_total_cost_twd * 100) if crypto_total_cost_twd else 0

    # 6. Insurance
    ins_items = []
    ins_total_mv_usd = 0.0
    ins_total_mv_twd = 0.0
    for row in INSURANCE:
        value = row.get("value", 0)
        rate = row.get("rate", 0)
        currency = row.get("currency", "USD")
        
        if currency == "TWD":
            mv_twd = value
            mv_usd = value / usd_twd if usd_twd else 0
        else:
            mv_usd = value
            mv_twd = value * usd_twd
            
        ins_total_mv_usd += mv_usd
        ins_total_mv_twd += mv_twd
        
        ins_items.append({
            "name": row["name"],
            "value": value,
            "currency": currency,
            "value_usd": mv_usd,
            "value_twd": mv_twd,
            "rate": rate
        })

    # 5. Bank Deposits
    bank_items = []
    bank_total_mv_twd = 0.0
    for row in BANK_DEPOSITS:
        amt = row["amount"]
        if row["currency"] == "USD":
            mv_twd = amt * usd_twd
        else:
            mv_twd = amt
            
        bank_total_mv_twd += mv_twd
        
        bank_items.append({
            "bank": row["bank"],
            "type": row["type"],
            "currency": row["currency"],
            "amount": amt,
            "mv_twd": mv_twd
        })

    # 3. Bonds
    bond_items = []
    bond_total_mv_usd = 0.0
    for row in US_BONDS:
        price = cached_close(row["symbol"])
        cost = row["cost"]
        shares = row["shares"]
        if price is None: price = cost
        mv_usd = price * shares
        cost_usd = cost * shares
        profit_usd = mv_usd - cost_usd
        profit_pct = (profit_usd / cost_usd * 100) if cost_usd else 0
        bond_total_mv_usd += mv_usd
        bond_items.append({"symbol": row["symbol"], "shares": shares, "cost_usd": cost, "price_usd": price, "mv_usd": mv_usd, "profit_pct": profit_pct})
    bond_total_mv_twd = bond_total_mv_usd * usd_twd
    bond_total_cost_usd = sum(r["cost"] * r["shares"] for r in US_BONDS)
    bond_total_cost_twd = bond_total_cost_usd * usd_twd
    bond_unrealized_twd = bond_total_mv_twd - bond_total_cost_twd
    bond_return_pct = (bond_unrealized_twd / bond_total_cost_twd * 100) if bond_total_cost_twd else 0

    # 4. Precious Metals
    metal_items = []
    metal_total_mv_usd = 0.0
    for row in PRECIOUS_METALS:
        price = cached_close(row["symbol"])
        cost = row["cost"]
        shares = row["shares"]
        if price is None: price = cost
        mv_usd = price * shares
        cost_usd = cost * shares
        profit_usd = mv_usd - cost_usd
        profit_pct = (profit_usd / cost_usd * 100) if cost_usd else 0
        metal_total_mv_usd += mv_usd
        metal_items.append({"symbol": row["symbol"], "shares": shares, "cost_usd": cost, "price_usd": price, "mv_usd": mv_usd, "profit_pct": profit_pct})
    metal_total_mv_twd = metal_total_mv_usd * usd_twd

    # 5. Commodities
    commodity_items = []
    commodity_total_mv_usd = 0.0
    for row in COMMODITIES:
        price = cached_close(row["symbol"])
        cost = row["cost"]
        shares = row["shares"]
        if price is None: price = cost
        mv_usd = price * shares
        cost_usd = cost * shares
        profit_usd = mv_usd - cost_usd
        profit_pct = (profit_usd / cost_usd * 100) if cost_usd else 0
        commodity_total_mv_usd += mv_usd
        commodity_items.append({"symbol": row["symbol"], "shares": shares, "cost_usd": cost, "price_usd": price, "mv_usd": mv_usd, "profit_pct": profit_pct})
    commodity_total_mv_twd = commodity_total_mv_usd * usd_twd

    # Combined: 貴金屬&原物料
    hard_items = metal_items + commodity_items
    hard_total_mv_usd = metal_total_mv_usd + commodity_total_mv_usd
    hard_total_mv_twd = metal_total_mv_twd + commodity_total_mv_twd
    hard_total_cost_usd = (sum(r["cost"] * r["shares"] for r in PRECIOUS_METALS) +
                           sum(r["cost"] * r["shares"] for r in COMMODITIES))
    hard_total_cost_twd = hard_total_cost_usd * usd_twd
    hard_unrealized_twd = hard_total_mv_twd - hard_total_cost_twd
    hard_return_pct = (hard_unrealized_twd / hard_total_cost_twd * 100) if hard_total_cost_twd else 0

    # Grand Totals
    grand_total_cost_twd = (us_total_cost_twd + tw_total_cost_twd + crypto_total_cost_twd +
                            bond_total_cost_twd + hard_total_cost_twd)
    grand_total_twd = us_total_mv_twd + tw_total_mv_twd + crypto_total_mv_twd + ins_total_mv_twd + bank_total_mv_twd + bond_total_mv_twd + hard_total_mv_twd
    grand_unrealized_twd = grand_total_twd - grand_total_cost_twd - ins_total_mv_twd - bank_total_mv_twd
    grand_return_pct = (grand_unrealized_twd / grand_total_cost_twd * 100) if grand_total_cost_twd else 0

    # Sort items by market value
    us_items.sort(key=lambda x: x["mv_usd"], reverse=True)
    tw_items.sort(key=lambda x: x["mv_twd"], reverse=True)
    crypto_items.sort(key=lambda x: x["mv_usd"], reverse=True)
    hard_items.sort(key=lambda x: x["mv_usd"], reverse=True)

    updated_at_tw = datetime.now(timezone("Asia/Taipei")).strftime("%Y-%m-%d %H:%M")

    return {
        "updated_at_tw": updated_at_tw,
        "usd_twd": usd_twd,
        "grand_total_twd": grand_total_twd,
        "grand_unrealized_twd": grand_unrealized_twd,
        "grand_return_pct": grand_return_pct,
        
        "us_total_mv_twd": us_total_mv_twd,
        "us_total_mv_usd": us_total_mv_usd,
        "us_unrealized_twd": us_unrealized_twd,
        "us_return_pct": us_return_pct,
        "us_items": us_items,
        
        "tw_total_mv_twd": tw_total_mv_twd,
        "tw_unrealized_twd": tw_unrealized_twd,
        "tw_return_pct": tw_return_pct,
        "tw_items": tw_items,
        
        "bond_total_mv_twd": bond_total_mv_twd,
        "bond_total_mv_usd": bond_total_mv_usd,
        "bond_unrealized_twd": bond_unrealized_twd,
        "bond_return_pct": bond_return_pct,
        "bond_items": bond_items,

        "hard_total_mv_twd": hard_total_mv_twd,
        "hard_total_mv_usd": hard_total_mv_usd,
        "hard_unrealized_twd": hard_unrealized_twd,
        "hard_return_pct": hard_return_pct,
        "hard_items": hard_items,
        
        "crypto_total_mv_twd": crypto_total_mv_twd,
        "crypto_total_mv_usd": crypto_total_mv_usd,
        "crypto_unrealized_twd": crypto_unrealized_twd,
        "crypto_return_pct": crypto_return_pct,
        "crypto_items": crypto_items,
        
        "ins_total_mv_twd": ins_total_mv_twd,
        "ins_total_mv_usd": ins_total_mv_usd,
        "ins_items": ins_items,
        
        "bank_total_mv_twd": bank_total_mv_twd,
        "bank_items": bank_items
    }


TEMPLATE = r"""<!doctype html>
<html lang="zh-TW">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chink 總資產紀錄 (Total Assets)</title>
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
            background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
        }

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

        .main {
            max-width: 1100px;
            margin: 32px auto 0;
            padding: 0 40px;
            display: grid;
            grid-template-columns: 320px 1fr;
            gap: 24px;
        }

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
        .stat-sub {
            font-size: .7rem;
            color: var(--text-dim);
            margin-top: 2px;
            font-family: 'Source Code Pro', monospace;
        }
        .gain { color: var(--green); }
        .loss { color: var(--red); }

        .chart-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 4px;
            padding: 28px;
        }
        .chart-inner {
            position: relative;
            height: 300px;
            margin-top: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .table-section {
            max-width: 1100px;
            margin: 32px auto 0;
            padding: 0 40px;
        }
        .table-header {
            font-size: .75rem;
            letter-spacing: 2px;
            text-transform: uppercase;
            color: var(--gold-light);
            padding: 0 0 12px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 12px;
            font-weight: 600;
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

        @media (max-width: 800px) {
            header { padding: 32px 20px 24px; flex-direction: column; align-items: flex-start; }
            header::after { left: 20px; }
            .main { padding: 0 20px; grid-template-columns: 1fr; }
            .table-section { padding: 0 20px; }
            footer { padding: 20px 20px 0; }
        }
    </style>
</head>
<body>

<header>
    <div>
        <div class="site-title">Chink Total Assets</div>
        <div class="site-subtitle">總資產紀錄 · 跨資產配置追蹤</div>
    </div>
    <div class="meta-time">
        <strong>Last Updated</strong>
        {{ updated_at_tw }} 台北時間<br>
        <span style="font-size: 0.6rem; color: var(--text-dim);">USD/TWD: {{ "%.2f"|format(usd_twd) }}</span>
    </div>
</header>

<div class="main">
    <div class="summary-card">
        <div class="summary-label">Total Assets Summary · 總資產總覽</div>

        <div class="stat-row">
            <div><div class="stat-name">總資產 (TWD)</div></div>
            <div style="text-align:right">
                <div class="stat-value" style="color: var(--gold-light); font-size: 1.2rem;">NT$ {{ "{:,.0f}".format(grand_total_twd) }}</div>
                <div class="stat-sub" style="margin-top:4px;">
                    未實現損益:
                    <span class="{% if grand_unrealized_twd >= 0 %}gain{% else %}loss{% endif %}">
                        {% if grand_unrealized_twd >= 0 %}+{% endif %}NT$ {{ "{:,.0f}".format(grand_unrealized_twd) }}
                    </span>
                    &nbsp;
                    <span class="{% if grand_return_pct >= 0 %}gain{% else %}loss{% endif %}">
                        ({% if grand_return_pct >= 0 %}+{% endif %}{{ "%.2f"|format(grand_return_pct) }}%)
                    </span>
                </div>
            </div>
        </div>
        
        <div class="stat-row">
            <div><div class="stat-name">1. 美股</div></div>
            <div style="text-align:right">
                <div class="stat-value">NT$ {{ "{:,.0f}".format(us_total_mv_twd) }}</div>
                <div class="stat-sub">USD {{ "{:,.0f}".format(us_total_mv_usd) }}</div>
                <div class="stat-sub">
                    <span class="{% if us_unrealized_twd >= 0 %}gain{% else %}loss{% endif %}">
                        {% if us_unrealized_twd >= 0 %}+{% endif %}NT$ {{ "{:,.0f}".format(us_unrealized_twd) }}
                        ({% if us_return_pct >= 0 %}+{% endif %}{{ "%.1f"|format(us_return_pct) }}%)
                    </span>
                </div>
            </div>
        </div>

        <div class="stat-row">
            <div><div class="stat-name">2. 台股</div></div>
            <div style="text-align:right">
                <div class="stat-value">NT$ {{ "{:,.0f}".format(tw_total_mv_twd) }}</div>
                <div class="stat-sub">
                    <span class="{% if tw_unrealized_twd >= 0 %}gain{% else %}loss{% endif %}">
                        {% if tw_unrealized_twd >= 0 %}+{% endif %}NT$ {{ "{:,.0f}".format(tw_unrealized_twd) }}
                        ({% if tw_return_pct >= 0 %}+{% endif %}{{ "%.1f"|format(tw_return_pct) }}%)
                    </span>
                </div>
            </div>
        </div>

        <div class="stat-row">
            <div><div class="stat-name">3. 美債</div></div>
            <div style="text-align:right">
                <div class="stat-value">NT$ {{ "{:,.0f}".format(bond_total_mv_twd) }}</div>
                <div class="stat-sub">USD {{ "{:,.0f}".format(bond_total_mv_usd) }}</div>
                <div class="stat-sub">
                    <span class="{% if bond_unrealized_twd >= 0 %}gain{% else %}loss{% endif %}">
                        {% if bond_unrealized_twd >= 0 %}+{% endif %}NT$ {{ "{:,.0f}".format(bond_unrealized_twd) }}
                        ({% if bond_return_pct >= 0 %}+{% endif %}{{ "%.1f"|format(bond_return_pct) }}%)
                    </span>
                </div>
            </div>
        </div>

        <div class="stat-row">
            <div><div class="stat-name">4. 貴金屬&amp;原物料</div></div>
            <div style="text-align:right">
                <div class="stat-value">NT$ {{ "{:,.0f}".format(hard_total_mv_twd) }}</div>
                <div class="stat-sub">USD {{ "{:,.0f}".format(hard_total_mv_usd) }}</div>
                <div class="stat-sub">
                    <span class="{% if hard_unrealized_twd >= 0 %}gain{% else %}loss{% endif %}">
                        {% if hard_unrealized_twd >= 0 %}+{% endif %}NT$ {{ "{:,.0f}".format(hard_unrealized_twd) }}
                        ({% if hard_return_pct >= 0 %}+{% endif %}{{ "%.1f"|format(hard_return_pct) }}%)
                    </span>
                </div>
            </div>
        </div>

        <div class="stat-row">
            <div><div class="stat-name">5. 儲蓄險</div></div>
            <div style="text-align:right">
                <div class="stat-value">NT$ {{ "{:,.0f}".format(ins_total_mv_twd) }}</div>
                <div class="stat-sub">USD {{ "{:,.0f}".format(ins_total_mv_usd) }}</div>
            </div>
        </div>
        
        <div class="stat-row">
            <div><div class="stat-name">6. 加密貨幣</div></div>
            <div style="text-align:right">
                <div class="stat-value">NT$ {{ "{:,.0f}".format(crypto_total_mv_twd) }}</div>
                <div class="stat-sub">USD {{ "{:,.0f}".format(crypto_total_mv_usd) }}</div>
                <div class="stat-sub">
                    <span class="{% if crypto_unrealized_twd >= 0 %}gain{% else %}loss{% endif %}">
                        {% if crypto_unrealized_twd >= 0 %}+{% endif %}NT$ {{ "{:,.0f}".format(crypto_unrealized_twd) }}
                        ({% if crypto_return_pct >= 0 %}+{% endif %}{{ "%.1f"|format(crypto_return_pct) }}%)
                    </span>
                </div>
            </div>
        </div>
        
        <div class="stat-row">
            <div><div class="stat-name">7. 銀行存款</div></div>
            <div style="text-align:right">
                <div class="stat-value">NT$ {{ "{:,.0f}".format(bank_total_mv_twd) }}</div>
            </div>
        </div>

    </div>

    <div class="chart-card">
        <div class="summary-label" style="border:none; margin-bottom:0;">Asset Allocation · 資產配置圓餅圖</div>
        <div class="chart-inner">
            <canvas id="allocationChart"></canvas>
        </div>
    </div>
</div>

<!-- 1. 美股 -->
<div class="table-section">
    <div class="table-header">1. 美股</div>
    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>代號 Symbol</th>
                    <th>現價 (USD)</th>
                    <th>成本 (USD)</th>
                    <th>股數</th>
                    <th>市值 (USD)</th>
                    <th>報酬率</th>
                </tr>
            </thead>
            <tbody>
                {% for it in us_items %}
                <tr>
                    <td>{{ it.symbol }}</td>
                    <td>{{ "%.2f"|format(it.price_usd) }}</td>
                    <td>{{ "%.2f"|format(it.cost_usd) }}</td>
                    <td>{{ "%.4f"|format(it.shares) }}</td>
                    <td>{{ "{:,.2f}".format(it.mv_usd) }}</td>
                    <td>
                        <span class="{% if it.profit_pct > 0 %}gain-cell{% elif it.profit_pct < 0 %}loss-cell{% endif %}">
                            {% if it.profit_pct > 0 %}+{% endif %}{{ "%.2f"|format(it.profit_pct) }}%
                        </span>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<!-- 2. 台股 -->
<div class="table-section">
    <div class="table-header">2. 台股</div>
    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>名稱 (代號)</th>
                    <th>現價 (TWD)</th>
                    <th>成本 (TWD)</th>
                    <th>股數</th>
                    <th>市值 (TWD)</th>
                    <th>報酬率</th>
                </tr>
            </thead>
            <tbody>
                {% for it in tw_items %}
                <tr>
                    <td>
                        {% if it.name %}{{ it.name }} ({{ it.symbol }}){% else %}{{ it.symbol }}{% endif %}
                    </td>
                    <td>{{ "%.2f"|format(it.price_twd) }}</td>
                    <td>{{ "%.2f"|format(it.cost_twd) }}</td>
                    <td>{{ "%.0f"|format(it.shares) }}</td>
                    <td>{{ "{:,.0f}".format(it.mv_twd) }}</td>
                    <td>
                        <span class="{% if it.profit_pct > 0 %}gain-cell{% elif it.profit_pct < 0 %}loss-cell{% endif %}">
                            {% if it.profit_pct > 0 %}+{% endif %}{{ "%.2f"|format(it.profit_pct) }}%
                        </span>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<!-- 3. 美債 -->
<div class="table-section">
    <div class="table-header">3. 美債</div>
    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>代號 Symbol</th>
                    <th>現價 (USD)</th>
                    <th>成本 (USD)</th>
                    <th>股數</th>
                    <th>市值 (USD)</th>
                    <th>報酬率</th>
                </tr>
            </thead>
            <tbody>
                {% for it in bond_items %}
                <tr>
                    <td>{{ it.symbol }}</td>
                    <td>{{ "%.2f"|format(it.price_usd) }}</td>
                    <td>{{ "%.2f"|format(it.cost_usd) }}</td>
                    <td>{{ "%.4f"|format(it.shares) }}</td>
                    <td>{{ "{:,.2f}".format(it.mv_usd) }}</td>
                    <td>
                        <span class="{% if it.profit_pct > 0 %}gain-cell{% elif it.profit_pct < 0 %}loss-cell{% endif %}">
                            {% if it.profit_pct > 0 %}+{% endif %}{{ "%.2f"|format(it.profit_pct) }}%
                        </span>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<!-- 4. 貴金屬&原物料 -->
<div class="table-section">
    <div class="table-header">4. 貴金屬&amp;原物料</div>
    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>代號 Symbol</th>
                    <th>現價 (USD)</th>
                    <th>成本 (USD)</th>
                    <th>數量</th>
                    <th>市值 (USD)</th>
                    <th>報酬率</th>
                </tr>
            </thead>
            <tbody>
                {% for it in hard_items %}
                <tr>
                    <td>{{ it.symbol }}</td>
                    <td>{{ "%.2f"|format(it.price_usd) }}</td>
                    <td>{{ "%.2f"|format(it.cost_usd) }}</td>
                    <td>{{ "%.4f"|format(it.shares) }}</td>
                    <td>{{ "{:,.2f}".format(it.mv_usd) }}</td>
                    <td>
                        <span class="{% if it.profit_pct > 0 %}gain-cell{% elif it.profit_pct < 0 %}loss-cell{% endif %}">
                            {% if it.profit_pct > 0 %}+{% endif %}{{ "%.2f"|format(it.profit_pct) }}%
                        </span>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<!-- 5. 儲蓄險 -->
<div class="table-section">
    <div class="table-header">5. 儲蓄險</div>
    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>名稱</th>
                    <th>幣別</th>
                    <th>保單價值</th>
                    <th>等值美金 (USD)</th>
                    <th>約當台幣 (TWD)</th>
                    <th>預定利率</th>
                </tr>
            </thead>
            <tbody>
                {% for it in ins_items %}
                <tr>
                    <td>{{ it.name }}</td>
                    <td>{{ it.currency }}</td>
                    <td>{{ "{:,.2f}".format(it.value) if it.currency == 'USD' else "{:,.0f}".format(it.value) }}</td>
                    <td>{{ "{:,.2f}".format(it.value_usd) }}</td>
                    <td>{{ "{:,.0f}".format(it.value_twd) }}</td>
                    <td style="color: var(--gold-light);">{{ "%.2f"|format(it.rate) }}%</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<!-- 7. 加密貨幣 -->
<div class="table-section">
    <div class="table-header">7. 加密貨幣</div>
    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>代號 Symbol</th>
                    <th>現價 (USD)</th>
                    <th>成本 (USD)</th>
                    <th>數量</th>
                    <th>市值 (USD)</th>
                    <th>報酬率</th>
                </tr>
            </thead>
            <tbody>
                {% for it in crypto_items %}
                <tr>
                    <td>{{ it.symbol }}</td>
                    <td>{{ "%.2f"|format(it.price_usd) }}</td>
                    <td>{{ "%.2f"|format(it.cost_usd) }}</td>
                    <td>{{ "%.4f"|format(it.shares) }}</td>
                    <td>{{ "{:,.2f}".format(it.mv_usd) }}</td>
                    <td>
                        <span class="{% if it.profit_pct > 0 %}gain-cell{% elif it.profit_pct < 0 %}loss-cell{% endif %}">
                            {% if it.profit_pct > 0 %}+{% endif %}{{ "%.2f"|format(it.profit_pct) }}%
                        </span>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<!-- 8. 銀行活存、定存、美金活存 -->
<div class="table-section">
    <div class="table-header">8. 銀行存款 (活存、定存、外幣)</div>
    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>銀行帳戶</th>
                    <th>類型</th>
                    <th>幣別</th>
                    <th>金額</th>
                    <th>約當台幣市值 (TWD)</th>
                </tr>
            </thead>
            <tbody>
                {% for it in bank_items %}
                <tr>
                    <td>{{ it.bank }}</td>
                    <td>{{ it.type }}</td>
                    <td>{{ it.currency }}</td>
                    <td>{{ "{:,.2f}".format(it.amount) }}</td>
                    <td>{{ "{:,.0f}".format(it.mv_twd) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<footer>
    資料來源：Yahoo Finance / 靜態設定 · 僅供個人資產追蹤參考
</footer>

<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2"></script>
<script>
    const ctx = document.getElementById('allocationChart').getContext('2d');
    const data = [
        {{ us_total_mv_twd }},
        {{ tw_total_mv_twd }},
        {{ bond_total_mv_twd }},
        {{ hard_total_mv_twd }},
        {{ ins_total_mv_twd }},
        {{ crypto_total_mv_twd }},
        {{ bank_total_mv_twd }}
    ];
    const rawLabels = [
        '美股',
        '台股',
        '美債',
        '貴金屬&原物料',
        '儲蓄險',
        '加密貨幣',
        '銀行存款'
    ];
    
    const total = data.reduce((a, b) => a + b, 0);
    const labelsWithPct = rawLabels.map((lbl, i) => {
        const pct = total > 0 ? ((data[i] / total) * 100).toFixed(1) + '%' : '0%';
        return `${lbl} (${pct})`;
    });

    Chart.register(ChartDataLabels);

    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labelsWithPct,
            datasets: [{
                data: data,
                backgroundColor: ['#4e9af1', '#f16b4e', '#5ebff2', '#c9a84c', '#b06cf7', '#f7884e', '#4ecf8a'],
                borderColor: '#0a0a0a',
                borderWidth: 2,
                hoverOffset: 8
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '55%',
            plugins: {
                legend: {
                    position: 'right',
                    labels: { color: '#9a9a9a', font: { family: "'Noto Sans TC', sans-serif", size: 11 } }
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
                            const fmt   = new Intl.NumberFormat('zh-TW', { style: 'currency', currency: 'TWD', maximumFractionDigits: 0 });
                            return ` ${fmt.format(value)}  (${pct}%)`;
                        }
                    }
                },
                datalabels: {
                    color: '#ffffff',
                    font: { family: "'Noto Sans TC', sans-serif", size: 11, weight: 'bold' },
                    formatter: function(value, context) {
                        const total = context.dataset.data.reduce((a, b) => a + b, 0);
                        const pct = ((value / total) * 100).toFixed(1);
                        if (parseFloat(pct) < 3) return '';
                        return rawLabels[context.dataIndex] + '\n' + pct + '%';
                    },
                    textAlign: 'center',
                    padding: 4
                }
            }
        }
    });
</script>

</body>
</html>
"""

@app.route("/")
def index():
    data = _build_assets_snapshot()
    return render_template_string(TEMPLATE, **data)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true", help="Run local server")
    args = parser.parse_args()

    if args.serve:
        print("Starting local server at http://127.0.0.1:5001")
        app.run(host="127.0.0.1", port=5001, debug=True)
    else:
        print("Please run with --serve to start the server.")
