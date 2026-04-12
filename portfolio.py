# -*- coding: utf-8 -*-
"""
Usage:
  pip install -r requirements.txt
  python portfolio.py --serve
  python portfolio.py --output docs/index.html

Local preview: http://127.0.0.1:5000/
"""

from flask import Flask, render_template_string
import re
from datetime import datetime, timedelta
import requests
import json
import threading, time, os, logging, argparse
from pytz import timezone
from pathlib import Path
import yfinance as yf
import pandas as pd
import numpy as np

app = Flask(__name__)

# ================== 持股設定 ==================
EXCLUDED_ETFS_US = set()

FULL_PORTFOLIO = [
    {"symbol": "TSM",   "shares": 65,        "cost": 311.863846},
    {"symbol": "SNPS",  "shares": 4,         "cost": 396.15},
    {"symbol": "YUM",   "shares": 1,         "cost": 141.34},
    {"symbol": "UNH",   "shares": 22,        "cost": 310.86},
    {"symbol": "GOOGL", "shares": 80.47318,  "cost": 185.028},
    {"symbol": "NVDA",  "shares": 48.22095,   "cost": 140.098},
    # {"symbol": "QCOM",  "shares": 12,        "cost": 161.4525},
    {"symbol": "MSFT",  "shares": 5,         "cost": 415.454},
    {"symbol": "MU",    "shares": 50,        "cost": 367.1426},
    {"symbol": "KO",    "shares": 83.47431,  "cost": 68.009},
    {"symbol": "AEP",   "shares": 15,        "cost": 105.216},
    {"symbol": "DUK",   "shares": 16,        "cost": 115.79375},
        {"symbol": "DPZ",   "shares": 2,        "cost": 368.735},
    {"symbol": "AXP",   "shares": 5,        "cost": 300.21},

    {"symbol": "MCD",   "shares": 10,        "cost": 303.413},
    {"symbol": "CEG",   "shares": 23,        "cost": 321.596},
    {"symbol": "LEU",   "shares": 18,        "cost": 265.216},
    {"symbol": "AMZN",  "shares": 18,        "cost": 220.786667},
    {"symbol": "ETN",   "shares": 2,         "cost": 341.46},
    {"symbol": "HUBB",  "shares": 4,         "cost": 413.425},
    {"symbol": "FSLR",  "shares": 10,         "cost": 221.928},
    # {"symbol": "VST",   "shares": 14,        "cost": 166.08},
    # {"symbol": "TSLA",  "shares": 5.51725,   "cost": 436.234},

]

WATCHLIST = [
    "AAPL", "META","DIS", "AMD", "COST", "GEV","VRT","JNJ"
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
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
    return None

def fetch_stock_pe(symbol):
    try:
        info = yf.Ticker(symbol).info
        return {
            "trailingPE": info.get("trailingPE"),
            "forwardPE": info.get("forwardPE")
        }
    except Exception as e:
        print(f"Error fetching PE for {symbol}: {e}")
        return {"trailingPE": None, "forwardPE": None}

def cached_stock_pe(symbol, ttl=3600):
    key = ("pe", symbol)
    entry = _get_cache(key)
    now = _now()
    if entry and (now - entry["ts"] < ttl):
        return entry["data"]
    data = fetch_stock_pe(symbol)
    _set_cache(key, {"ts": now, "data": data})
    return data

def _build_core_rows():
    return [r for r in FULL_PORTFOLIO if r["symbol"] not in EXCLUDED_ETFS_US]


CNN_FNG_BASE_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/"

SP500_FPE_SOURCE_URL = "https://www.multpl.com/s-p-500-pe-ratio"
SP500_FPE_FORWARD_URL = "https://www.multpl.com/s-p-500-pe-ratio/table/by-month"
SP500_TRAILING_URL    = "https://www.multpl.com/s-p-500-pe-ratio/table/by-month"
SP500_SHILLER_URL     = "https://www.multpl.com/shiller-pe/table/by-month"

def _parse_multpl_pe(url):
    """
    從 multpl.com 抓 S&P 500 P/E 表格，回傳最新兩筆 (date, value)。
    multpl 是靜態 HTML，不需要 JS 執行，不會被反爬蟲擋。
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        # 表格格式: <td>Apr 1, 2026</td><td>21.5</td>
        rows = re.findall(
            r'<tr[^>]*>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>\s*</tr>',
            r.text
        )
        results = []
        for date_str, val_str in rows:
            val_str = val_str.strip().replace(",", "")
            # Remove HTML entities like &#x2002; before finding the number
            val_str = re.sub(r'&#[^;]+;', '', val_str)
            num_match = re.search(r'(-?\d+(?:\.\d+)?)', val_str)
            if num_match:
                try:
                    results.append((date_str.strip(), float(num_match.group(1))))
                except ValueError:
                    pass
        return results
    except Exception as e:
        print(f"_parse_multpl_pe error: {e}")
        return []


def fetch_macromicro_sp500_forward_pe():
    """
    從 multpl.com 抓 S&P 500 Trailing P/E（月度）作為估值指標。
    multpl.com 是靜態 HTML 網站，沒有 Cloudflare 反爬蟲，穩定可靠。
    注意：這是 Trailing P/E（過去12月實際EPS），非 Forward P/E（分析師預估）。
    Forward P/E 通常比 Trailing 低 10~20%，估值分區已做對應調整。
    """
    default_payload = {
        'value': None,
        'value_str': 'N/A',
        'prev_value': None,
        'prev_value_str': 'N/A',
        'delta': None,
        'delta_str': 'N/A',
        'date': 'N/A',
        'valuation': 'N/A',
        'source_name': 'Multpl.com / S&P 500 Trailing P/E',
        'source_url': SP500_FPE_SOURCE_URL,
    }

    try:
        rows = _parse_multpl_pe(SP500_TRAILING_URL)
        if len(rows) < 2:
            print("multpl.com: 資料不足")
            return default_payload

        date_text, latest_value = rows[0]
        _,          prev_value  = rows[1]
        delta_value = latest_value - prev_value

        # Trailing P/E 估值分區（比 Forward P/E 高，門檻相應上移）
        if latest_value >= 28:
            valuation = '偏貴'
        elif latest_value >= 22:
            valuation = '中高'
        elif latest_value >= 18:
            valuation = '中性'
        else:
            valuation = '偏便宜'

        return {
            'value': latest_value,
            'value_str': f'{latest_value:.2f}',
            'prev_value': prev_value,
            'prev_value_str': f'{prev_value:.2f}',
            'delta': delta_value,
            'delta_str': f'{delta_value:+.2f}',
            'date': date_text,
            'valuation': valuation,
            'source_name': 'Multpl.com / S&P 500 Trailing P/E',
            'source_url': SP500_FPE_SOURCE_URL,
        }
    except Exception as e:
        print(f'Error fetching S&P 500 P/E: {e}')
        return default_payload

def cached_sp500_forward_pe(ttl=_TTL_NORMAL):
    key = ('mm_sp500_forward_pe',)
    entry = _get_cache(key)
    now = _now()
    if entry and (now - entry['ts'] < ttl):
        return entry['data']
    data = fetch_macromicro_sp500_forward_pe()
    _set_cache(key, {'ts': now, 'data': data})
    return data


def fetch_shiller_pe():
    default_payload = {
        'value': None,
        'value_str': 'N/A',
        'prev_value': None,
        'prev_value_str': 'N/A',
        'delta': None,
        'delta_str': 'N/A',
        'date': 'N/A',
        'valuation': 'N/A',
        'source_name': 'Multpl.com / Shiller P/E',
        'source_url': SP500_SHILLER_URL,
    }
    try:
        rows = _parse_multpl_pe(SP500_SHILLER_URL)
        if len(rows) < 2: return default_payload
        date_text, latest_value = rows[0]
        _, prev_value = rows[1]
        delta_value = latest_value - prev_value
        
        if latest_value >= 30: valuation = '泡沫高估區'
        elif latest_value >= 25: valuation = '偏貴'
        elif latest_value >= 20: valuation = '中性偏高'
        elif latest_value >= 15: valuation = '合理偏便宜'
        else: valuation = '十年一遇歷史大底(15下)'
        
        return {
            'value': latest_value,
            'value_str': f'{latest_value:.2f}',
            'prev_value': prev_value,
            'prev_value_str': f'{prev_value:.2f}',
            'delta': delta_value,
            'delta_str': f'{delta_value:+.2f}',
            'date': date_text,
            'valuation': valuation,
            'source_name': 'Multpl.com / Shiller P/E',
            'source_url': SP500_SHILLER_URL,
        }
    except Exception as e:
        print(f"Error fetching Shiller PE: {e}")
        return default_payload

def cached_shiller_pe(ttl=_TTL_NORMAL):
    key = ('shiller_pe',)
    entry = _get_cache(key)
    now = _now()
    if entry and (now - entry['ts'] < ttl):
        return entry['data']
    data = fetch_shiller_pe()
    _set_cache(key, {'ts': now, 'data': data})
    return data

def fetch_finra_margin():
    try:
        url = "https://www.finra.org/investors/learn-to-invest/advanced-investing/margin-statistics"
        r = requests.get(url, headers=HEADERS, timeout=15)
        html = r.text
        m = re.search(r'<tbody>(.*?)</tbody>', html, re.DOTALL)
        if not m: return None
        
        rows = re.findall(r'<tr>(.*?)</tr>', m.group(1))
        data = []
        for row in rows:
            tds = re.findall(r'<td>(.*?)</td>', row)
            if len(tds) >= 2:
                month = tds[0].strip()
                val = int(tds[1].strip().replace(",", ""))
                data.append((month, val))
        
        if len(data) >= 2:
            mom_pct = (data[0][1] - data[1][1]) / data[1][1] * 100
            return {
                "latest_month": data[0][0],
                "latest_val": data[0][1],
                "val_str": f"{data[0][1]:,}",
                "prev_month": data[1][0],
                "prev_val": data[1][1],
                "mom_pct": mom_pct,
                "mom_str": f"{mom_pct:+.2f}%"
            }
    except Exception as e:
        print("Finra margin error", e)
    return None

def cached_finra_margin(ttl=_TTL_NORMAL):
    key = ('finra_margin',)
    entry = _get_cache(key)
    now = _now()
    if entry and (now - entry['ts'] < ttl):
        return entry['data']
    data = fetch_finra_margin()
    _set_cache(key, {'ts': now, 'data': data})
    return data

def fetch_stock_technicals(symbol):
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?range=1y&interval=1d"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            result = data.get('chart', {}).get('result')
            if result:
                indicators = result[0].get('indicators', {}).get('quote', [{}])[0]
                highs = indicators.get('high', [])
                closes = indicators.get('close', [])
                valid_highs = [h for h in highs if h is not None]
                valid_closes = [c for c in closes if c is not None]
                if not valid_highs or not valid_closes: return None
                
                max_high = max(valid_highs)
                meta = result[0].get('meta', {})
                current_price = meta.get('regularMarketPrice') or meta.get('chartPreviousClose')
                
                dd = None
                if max_high and current_price:
                    dd = (current_price - max_high) / max_high * 100
                
                ma60 = sum(valid_closes[-60:])/60 if len(valid_closes) >= 60 else None
                ma250 = sum(valid_closes[-250:])/len(valid_closes) if len(valid_closes) >= 200 else None
                
                return {
                    "dd": dd,
                    "ma60": ma60,
                    "ma250": ma250,
                    "price": current_price
                }
    except Exception as e:
        print(f"Error fetching technicals for {symbol}: {e}")
    return None

def cached_stock_technicals(symbol, ttl=_TTL_NORMAL):
    key = ("technicals", symbol)
    entry = _get_cache(key)
    now = _now()
    if entry and (now - entry["ts"] < ttl) and entry["data"] is not None:
        return entry["data"]
    data = fetch_stock_technicals(symbol)
    if data is not None:
        _set_cache(key, {"ts": now, "data": data})
        return data
    elif entry and entry["data"] is not None:
        return entry["data"]
    return None

def fetch_portfolio_metrics(core_rows):
    try:
        symbols = [r["symbol"] for r in core_rows]
        if not symbols: return None
        tickers = symbols + ["^GSPC"]
        data = yf.download(tickers, period="ytd", interval="1d", progress=False)["Close"]
        
        data = data.ffill().bfill()
        sp500_returns = data["^GSPC"].pct_change().dropna()
        
        port_val = pd.Series(0.0, index=data.index)
        for r in core_rows:
            sym = r["symbol"]
            shares = r["shares"]
            if sym in data.columns:
                port_val += data[sym] * shares
                
        port_returns = port_val.pct_change().dropna()
        aligned = pd.concat([port_returns, sp500_returns], axis=1).dropna()
        p_ret = aligned.iloc[:, 0]
        s_ret = aligned.iloc[:, 1]
        
        rf = 0.04 / 252 # Assumed 4% annual risk-free rate
        excess_returns = p_ret - rf
        std_dev = excess_returns.std()
        sharpe_ratio = 0 if std_dev == 0 else np.sqrt(252) * excess_returns.mean() / std_dev
            
        cov_matrix = np.cov(p_ret, s_ret)
        beta = cov_matrix[0, 1] / cov_matrix[1, 1] if cov_matrix[1, 1] != 0 else 1
        
        ann_port_return = (p_ret + 1).prod() - 1
        ann_sp500_return = (s_ret + 1).prod() - 1
        ytd_rf = (0.04 / 252) * len(p_ret)
        alpha = ann_port_return - (ytd_rf + beta * (ann_sp500_return - ytd_rf))
        
        return {
            "sharpe_str": f"{sharpe_ratio:.2f}",
            "beta_str": f"{beta:.2f}",
            "alpha_str": f"{alpha:.4f}",
            "sp500_ytd_ret_str": f"{ann_sp500_return * 100:.2f}%",
            "port_ytd_ret_str": f"{ann_port_return * 100:.2f}%"
        }
    except Exception as e:
        print(f"Error calculating portfolio metrics: {e}")
        return None

def cached_portfolio_metrics(core_rows, ttl=3600):
    key = ("port_metrics",)
    entry = _get_cache(key)
    now = _now()
    if entry and (now - entry["ts"] < ttl) and entry["data"] is not None:
        return entry["data"]
    data = fetch_portfolio_metrics(core_rows)
    if data is not None:
        _set_cache(key, {"ts": now, "data": data})
        return data
    elif entry and entry["data"] is not None:
        return entry["data"]
    return {"sharpe_str": "N/A", "beta_str": "N/A", "alpha_str": "N/A", "sp500_ytd_ret_str": "N/A", "port_ytd_ret_str": "N/A"}

def fetch_sp500_historical():
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/^GSPC?range=5y&interval=1d"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            data = r.json()
            result = data.get('chart', {}).get('result', [])
            if result:
                timestamps = result[0].get('timestamp', [])
                indicators = result[0].get('indicators', {}).get('quote', [{}])[0]
                closes = indicators.get('close', [])
                
                valid = [(ts, c) for ts, c in zip(timestamps, closes) if c is not None]
                if not valid: return None
                
                c_vals = [x[1] for x in valid]
                curr = c_vals[-1]
                
                ma20 = sum(c_vals[-20:])/20 if len(c_vals) >= 20 else None
                ma60 = sum(c_vals[-60:])/60 if len(c_vals) >= 60 else None
                ma250 = sum(c_vals[-250:])/250 if len(c_vals) >= 250 else None
                ma1250 = sum(c_vals[-1250:])/1250 if len(c_vals) >= 1250 else None
                
                chart_data = valid[-250:] # last 1 year
                labels = [datetime.fromtimestamp(ts, tz=timezone("Asia/Taipei")).strftime("%y/%m/%d") for ts, _ in chart_data]
                points = [round(v, 2) for _, v in chart_data]
                
                return {
                    "price_str": f"{curr:.2f}",
                    "ma20_str": f"{ma20:.2f}" if ma20 else "N/A",
                    "ma60_str": f"{ma60:.2f}" if ma60 else "N/A",
                    "ma250_str": f"{ma250:.2f}" if ma250 else "N/A",
                    "ma1250_str": f"{ma1250:.2f}" if ma1250 else "N/A",
                    "broken_20": curr < ma20 if ma20 else False,
                    "broken_60": curr < ma60 if ma60 else False,
                    "broken_250": curr < ma250 if ma250 else False,
                    "broken_1250": curr < ma1250 if ma1250 else False,
                    "chart_labels": json.dumps(labels),
                    "chart_points": json.dumps(points)
                }
    except Exception as e:
        print(f"Error fetching SP500 historical: {e}")
    return None

def cached_sp500_historical(ttl=_TTL_NORMAL):
    key = ("sp500_hist",)
    entry = _get_cache(key)
    now = _now()
    if entry and (now - entry["ts"] < ttl) and entry["data"] is not None:
        return entry["data"]
    data = fetch_sp500_historical()
    if data is not None:
        _set_cache(key, {"ts": now, "data": data})
        return data
    elif entry and entry["data"] is not None:
        return entry["data"]
    return None



def _format_fg_block(block):
    score = block.get("score")
    rating = block.get("rating")
    if score is None:
        return {"score": None, "score_str": "N/A", "rating": "N/A"}
    score = float(score)
    return {
        "score": score,
        "score_str": f"{score:.0f}",
        "rating": rating or fear_greed_label(score),
    }

def _nearest_historical_value(chart_points, target_dt):
    if not chart_points:
        return None
    best = min(chart_points, key=lambda p: abs((p["dt"] - target_dt).total_seconds()))
    return float(best["value"]) if best.get("value") is not None else None

def fear_greed_label(score):
    """Match CNN Fear & Greed gauge buckets exactly.

    0-24   : Extreme Fear
    25-44  : Fear
    45-55  : Neutral
    56-74  : Greed
    75-100 : Extreme Greed
    """
    if score is None:
        return "N/A"
    score = float(score)
    if 0 <= score <= 24:
        return "極度恐懼"
    if 25 <= score <= 44:
        return "恐懼"
    if 45 <= score <= 55:
        return "中性"
    if 56 <= score <= 74:
        return "貪婪"
    if 75 <= score <= 100:
        return "極度貪婪"
    return "N/A"

def fetch_cnn_fear_greed(days=370):
    now_tw = datetime.now(timezone("Asia/Taipei"))
    start_date = (now_tw - timedelta(days=days)).strftime("%Y-%m-%d")
    url = f"{CNN_FNG_BASE_URL}{start_date}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()

        now_block = data.get("fear_and_greed", {})
        historical = data.get("fear_and_greed_historical", {}).get("data", [])

        chart_points = []
        for point in historical:
            ts = point.get("x")
            val = point.get("y")
            if ts is None or val is None:
                continue
            dt = datetime.fromtimestamp(int(ts) / 1000, tz=timezone("Asia/Taipei"))
            chart_points.append({"dt": dt, "date": dt.strftime("%m/%d"), "value": float(val)})

        current_value = now_block.get("score")
        if current_value is None and chart_points:
            current_value = chart_points[-1]["value"]

        previous_close = now_block.get("previous_close")
        if previous_close is None and len(chart_points) >= 2:
            previous_close = chart_points[-2]["value"]

        week_block = _format_fg_block(data.get("fear_and_greed_week_ago", {}))
        month_block = _format_fg_block(data.get("fear_and_greed_month_ago", {}))
        year_block = _format_fg_block(data.get("fear_and_greed_year_ago", {}))

        if week_block["score"] is None:
            week_score = _nearest_historical_value(chart_points, now_tw - timedelta(days=7))
            week_block = {"score": week_score, "score_str": f"{week_score:.0f}" if week_score is not None else "N/A", "rating": fear_greed_label(week_score) if week_score is not None else "N/A"}
        if month_block["score"] is None:
            month_score = _nearest_historical_value(chart_points, now_tw - timedelta(days=30))
            month_block = {"score": month_score, "score_str": f"{month_score:.0f}" if month_score is not None else "N/A", "rating": fear_greed_label(month_score) if month_score is not None else "N/A"}
        if year_block["score"] is None:
            year_score = _nearest_historical_value(chart_points, now_tw - timedelta(days=365))
            year_block = {"score": year_score, "score_str": f"{year_score:.0f}" if year_score is not None else "N/A", "rating": fear_greed_label(year_score) if year_score is not None else "N/A"}

        recent_chart_points = chart_points[-90:]

        vix_data = data.get("market_volatility_vix", {}).get("data", [])
        latest_vix = vix_data[-1].get("y") if vix_data else None

        pcr_data = data.get("put_call_options", {}).get("data", [])
        latest_pcr = pcr_data[-1].get("y") if pcr_data else None

        return {
            "score": float(current_value) if current_value is not None else None,
            "rating": now_block.get("rating") or fear_greed_label(float(current_value)) if current_value is not None else "N/A",
            "previous_close": float(previous_close) if previous_close is not None else None,
            "previous_close_rating": fear_greed_label(previous_close) if previous_close is not None else "N/A",
            "week_ago": week_block,
            "month_ago": month_block,
            "year_ago": year_block,
            "chart_labels": json.dumps([p["date"] for p in recent_chart_points], ensure_ascii=False),
            "chart_data": json.dumps([p["value"] for p in recent_chart_points], ensure_ascii=False),
            "vix": latest_vix,
            "pcr": latest_pcr,
        }
    except Exception as e:
        print(f"Error fetching CNN Fear & Greed Index: {e}")
        return {
            "score": None,
            "rating": "N/A",
            "previous_close": None,
            "chart_labels": json.dumps([]),
            "chart_data": json.dumps([]),
            "vix": None,
            "pcr": None,
        }

def cached_fear_greed(ttl=_TTL_NORMAL):
    key = ("cnn_fear_greed",)
    entry = _get_cache(key)
    now = _now()
    if entry and (now - entry["ts"] < ttl):
        return entry["data"]
    data = fetch_cnn_fear_greed(days=90)
    _set_cache(key, {"ts": now, "data": data})
    return data


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

        pe_data = cached_stock_pe(row["symbol"])
        tpe_str = f"{pe_data['trailingPE']:.1f}" if pe_data and pe_data.get('trailingPE') else "N/A"
        fpe_str = f"{pe_data['forwardPE']:.1f}" if pe_data and pe_data.get('forwardPE') else "N/A"

        core_total_mv += mv
        tech = cached_stock_technicals(row["symbol"], ttl=_TTL_NORMAL) or {}
        ma60 = tech.get("ma60")
        ma250 = tech.get("ma250")
        bias_60 = ((price - ma60) / ma60 * 100) if price and ma60 else None
        broken_250 = (price < ma250) if price and ma250 else False

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
            "bias_60": bias_60,
            "bias_60_str": f"{bias_60:+.1f}%" if bias_60 is not None else "N/A",
            "dd_str": f"{tech.get('dd'):.1f}%" if tech.get('dd') is not None else "N/A",
            "broken_250": broken_250,
            "tpe_str": tpe_str,
            "fpe_str": fpe_str
        })

    core_total_cost = sum(r["cost"] * r["shares"] for r in core_rows)
    core_total_profit = sum(it["profit"] for it in core_items)
    core_total_pct = (core_total_profit / core_total_cost * 100) if core_total_cost else 0.0

    port_metrics = cached_portfolio_metrics(core_rows)

    core_items.sort(key=lambda x: x["market_value"], reverse=True)

    top_10 = core_items[:10]
    chart_labels = [item['symbol'] for item in top_10]
    chart_data = [round(item['market_value'], 2) for item in top_10]

    others_mv = sum(item['market_value'] for item in core_items[10:])
    if others_mv > 0:
        chart_labels.append('Others')
        chart_data.append(round(others_mv, 2))

    chart_logos = []
    for label in chart_labels:
        if label == 'Others':
            chart_logos.append("")
        else:
            chart_logos.append(f"https://assets.parqet.com/logos/symbol/{label}?format=png")

    sp500_fpe = cached_sp500_forward_pe(ttl=_TTL_NORMAL)
    finra_margin = cached_finra_margin(ttl=_TTL_NORMAL) or {}

    fear_greed = cached_fear_greed(ttl=_TTL_NORMAL)
    fg_score = fear_greed["score"]
    fg_prev = fear_greed["previous_close"]
    fg_delta = (fg_score - fg_prev) if (fg_score is not None and fg_prev is not None) else None
    fg_week = fear_greed.get("week_ago", {"score_str": "N/A", "rating": "N/A"})
    fg_month = fear_greed.get("month_ago", {"score_str": "N/A", "rating": "N/A"})
    fg_year = fear_greed.get("year_ago", {"score_str": "N/A", "rating": "N/A"})

    # Fetch Drawdowns
    sp5_hist = cached_sp500_historical(ttl=_TTL_NORMAL) or {}
    sp5_tech = cached_stock_technicals("^GSPC", ttl=_TTL_NORMAL) or {}
    sp500_dd = sp5_tech.get("dd")

    watchlist_items = []
    for sym in WATCHLIST:
        tech = cached_stock_technicals(sym, ttl=_TTL_NORMAL) or {}
        w_price = tech.get("price")
        w_ma60 = tech.get("ma60")
        w_ma250 = tech.get("ma250")
        w_dd = tech.get("dd")
        
        pe_data = cached_stock_pe(sym, ttl=3600)
        w_tpe_str = f"{pe_data['trailingPE']:.1f}" if pe_data and pe_data.get('trailingPE') else "N/A"
        w_fpe_str = f"{pe_data['forwardPE']:.1f}" if pe_data and pe_data.get('forwardPE') else "N/A"
        
        bias_60 = (w_price - w_ma60) / w_ma60 * 100 if w_price and w_ma60 else None
        is_broken_250 = w_price < w_ma250 if w_price and w_ma250 else False
        is_dd_20 = w_dd is not None and w_dd <= -20
        
        alerts = []
        if is_dd_20: alerts.append("回檔 > 20%")
        if is_broken_250: alerts.append("跌破年線")
        if not alerts and w_price and w_ma60 and bias_60 < -10: alerts.append("距季線 <-10%")
        
        watchlist_items.append({
            "symbol": sym,
            "price_str": f"{w_price:.2f}" if w_price else "N/A",
            "tpe_str": w_tpe_str,
            "fpe_str": w_fpe_str,
            "bias_60": bias_60,
            "dd_str": f"{w_dd:.1f}%" if w_dd is not None else "N/A",
            "alerts": alerts,
            "is_alert": bool(alerts)
        })

    # Strategy Conditions
    vix_val = fear_greed.get("vix")
    pcr_val = fear_greed.get("pcr")
    mom_val = finra_margin.get("mom_pct")

    sp5_b60 = sp5_hist.get("broken_60", False)
    sp5_b250 = sp5_hist.get("broken_250", False)
    sp5_b1250 = sp5_hist.get("broken_1250", False)

    # Class B Conditions (formerly A)
    b_cond_sp500 = sp500_dd is not None and sp500_dd <= -10
    b_cond_vix = vix_val is not None and vix_val > 30
    b_cond_pcr = pcr_val is not None and pcr_val > 0.9
    b_cond_finra = mom_val is not None and mom_val < 0
    b_cond_ma60 = sp5_b60
    b_cond_fg = fg_score is not None and fg_score < 15
    
    b_conds_met = sum([b_cond_sp500, b_cond_vix, b_cond_pcr, b_cond_finra, b_cond_ma60, b_cond_fg])
    b_class_signal = b_conds_met >= 4

    # Class A Conditions (formerly S)
    a_cond_sp500 = sp500_dd is not None and sp500_dd <= -15
    a_cond_vix = vix_val is not None and (vix_val > 35 or vix_val > 40)
    a_cond_pcr = pcr_val is not None and pcr_val > 1.0
    a_cond_finra_cont = mom_val is not None and mom_val < 0
    a_cond_ma250 = sp5_b250
    a_cond_pe = sp500_fpe.get("value") is not None and sp500_fpe["value"] < 25
    a_cond_fg = fg_score is not None and fg_score < 10

    a_conds_met = sum([a_cond_sp500, a_cond_vix, a_cond_pcr, a_cond_finra_cont, a_cond_ma250, a_cond_pe, a_cond_fg])
    a_class_signal = a_conds_met >= 5
    
    # Class S Conditions (New)
    s_cond_sp500 = sp500_dd is not None and sp500_dd <= -20
    s_cond_vix = vix_val is not None and (vix_val > 35 or vix_val > 40)
    s_cond_pcr = pcr_val is not None and pcr_val > 1.0
    s_cond_finra_cont = mom_val is not None and mom_val < 0
    s_cond_pe = sp500_fpe.get("value") is not None and sp500_fpe["value"] < 15
    s_cond_fg = fg_score is not None and fg_score < 5
    s_cond_ma1250 = sp5_b1250
    
    s_conds_met = sum([s_cond_sp500, s_cond_vix, s_cond_pcr, s_cond_finra_cont, s_cond_pe, s_cond_fg, s_cond_ma1250])
    s_class_signal = s_conds_met >= 5

    # Class SS Conditions (New)
    shiller_pe = cached_shiller_pe(ttl=_TTL_NORMAL)
    ss_cond_sp500 = sp500_dd is not None and sp500_dd <= -30
    ss_cond_vix = vix_val is not None and vix_val > 40
    ss_cond_shiller = shiller_pe.get("value") is not None and shiller_pe["value"] < 20
    ss_cond_pcr = pcr_val is not None and pcr_val > 1.2
    ss_cond_ma1250 = sp5_b1250
    
    ss_conds_met = sum([ss_cond_sp500, ss_cond_vix, ss_cond_shiller, ss_cond_ma1250, ss_cond_pcr])
    ss_class_signal = ss_conds_met >= 4

    # Day-of-year index for daily quote rotation
    day_of_year = datetime.now(timezone("Asia/Taipei")).timetuple().tm_yday

    return {
        "updated_at_tw": updated_at_tw,
        "core_items": core_items,
        "core_total_mv": core_total_mv,
        "core_total_cost": core_total_cost,
        "core_total_profit": core_total_profit,
        "core_total_pct": core_total_pct,
        "port_sharpe": port_metrics["sharpe_str"],
        "port_beta": port_metrics["beta_str"],
        "port_alpha": port_metrics["alpha_str"],
        "port_sp500_ret": port_metrics["sp500_ytd_ret_str"],
        "port_ytd_ret": port_metrics["port_ytd_ret_str"],
        "chart_labels": json.dumps(chart_labels),
        "chart_data": json.dumps(chart_data),
        "chart_logos": json.dumps(chart_logos),
        "fear_greed_score": fg_score,
        "fear_greed_score_str": f"{fg_score:.0f}" if fg_score is not None else "N/A",
        "fear_greed_rating": fear_greed.get("rating", "N/A"),
        "fear_greed_prev_str": f"{fg_prev:.0f}" if fg_prev is not None else "N/A",
        "fear_greed_prev_rating": fear_greed.get("previous_close_rating", "N/A"),
        "fear_greed_week_score_str": fg_week.get("score_str", "N/A"),
        "fear_greed_week_rating": fg_week.get("rating", "N/A"),
        "fear_greed_month_score_str": fg_month.get("score_str", "N/A"),
        "fear_greed_month_rating": fg_month.get("rating", "N/A"),
        "fear_greed_year_score_str": fg_year.get("score_str", "N/A"),
        "fear_greed_year_rating": fg_year.get("rating", "N/A"),
        "fear_greed_delta": fg_delta,
        "fear_greed_delta_str": f"{fg_delta:+.0f}" if fg_delta is not None else "N/A",
        "fear_greed_chart_labels": fear_greed.get("chart_labels", "[]"),
        "fear_greed_chart_data": fear_greed.get("chart_data", "[]"),
        "sp500_fpe_value_str": sp500_fpe["value_str"],
        "sp500_fpe_prev_value_str": sp500_fpe["prev_value_str"],
        "sp500_fpe_delta": sp500_fpe["delta"],
        "sp500_fpe_delta_str": sp500_fpe["delta_str"],
        "sp500_fpe_date": sp500_fpe["date"],
        "sp500_fpe_valuation": sp500_fpe["valuation"],
        "sp500_fpe_source_name": sp500_fpe["source_name"],
        "sp500_fpe_source_url": sp500_fpe["source_url"],
        "watchlist_items": watchlist_items,
        "day_of_year": day_of_year,
        "finra_val_str": finra_margin.get("val_str", "N/A"),
        "finra_month": finra_margin.get("latest_month", "N/A"),
        "finra_mom": finra_margin.get("mom_pct"),
        "finra_mom_str": finra_margin.get("mom_str", "N/A"),
        "vix": fear_greed.get("vix"),
        "vix_str": f"{fear_greed.get('vix'):.2f}" if fear_greed.get("vix") is not None else "N/A",
        "pcr": fear_greed.get("pcr"),
        "pcr_str": f"{fear_greed.get('pcr'):.2f}" if fear_greed.get("pcr") is not None else "N/A",
        
        # Strategy variables
        "sp500_dd_str": f"{sp500_dd:.1f}%" if sp500_dd is not None else "N/A",
        "b_cond_sp500": b_cond_sp500,
        "b_cond_vix": b_cond_vix,
        "b_cond_pcr": b_cond_pcr,
        "b_cond_finra": b_cond_finra,
        "b_cond_ma60": b_cond_ma60,
        "b_cond_fg": b_cond_fg,
        "b_conds_met": b_conds_met,
        "b_class_signal": b_class_signal,
        
        "a_cond_sp500": a_cond_sp500,
        "a_cond_vix": a_cond_vix,
        "a_cond_pcr": a_cond_pcr,
        "a_cond_finra_cont": a_cond_finra_cont,
        "a_cond_ma250": a_cond_ma250,
        "a_cond_pe": a_cond_pe,
        "a_cond_fg": a_cond_fg,
        "a_conds_met": a_conds_met,
        "a_class_signal": a_class_signal,

        "s_cond_sp500": s_cond_sp500,
        "s_cond_vix": s_cond_vix,
        "s_cond_pcr": s_cond_pcr,
        "s_cond_finra_cont": s_cond_finra_cont,
        "s_cond_pe": s_cond_pe,
        "s_cond_fg": s_cond_fg,
        "s_cond_ma1250": s_cond_ma1250,
        "s_conds_met": s_conds_met,
        "s_class_signal": s_class_signal,

        "ss_cond_sp500": ss_cond_sp500,
        "ss_cond_vix": ss_cond_vix,
        "ss_cond_shiller": ss_cond_shiller,
        "ss_cond_pcr": ss_cond_pcr,
        "ss_cond_ma1250": s_cond_ma1250,
        "ss_conds_met": ss_conds_met,
        "ss_class_signal": ss_class_signal,
        
        "shiller_pe_value_str": shiller_pe.get("value_str", "N/A"),
        "shiller_pe_valuation": shiller_pe.get("valuation", "N/A"),
        
        "sp5_price": sp5_hist.get("price_str", "N/A"),
        "sp5_ma20": sp5_hist.get("ma20_str", "N/A"),
        "sp5_ma60": sp5_hist.get("ma60_str", "N/A"),
        "sp5_ma250": sp5_hist.get("ma250_str", "N/A"),
        "sp5_ma1250": sp5_hist.get("ma1250_str", "N/A"),
        "sp5_b20": sp5_hist.get("broken_20", False),
        "sp5_b60": sp5_hist.get("broken_60", False),
        "sp5_b250": sp5_hist.get("broken_250", False),
        "sp5_b1250": sp5_hist.get("broken_1250", False),
        "sp5_chart_labels": sp5_hist.get("chart_labels", "[]"),
        "sp5_chart_points": sp5_hist.get("chart_points", "[]"),
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
        .full-width-card {
            max-width: 1100px;
            margin: 24px auto 0;
            padding: 28px 40px;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 4px;
        }
        .fear-greed-grid {
            display: grid;
            grid-template-columns: 260px 1fr;
            gap: 24px;
            align-items: stretch;
        }
        .fear-greed-score {
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 10px;
            padding-right: 12px;
            border-right: 1px solid var(--border);
        }
        .fear-greed-snapshot-table {
            display: flex;
            flex-direction: column;
            margin-bottom: 12px;
            border-bottom: 1px solid var(--border);
        }
        .fear-greed-snapshot-row {
            display: grid;
            grid-template-columns: 1fr auto;
            align-items: center;
            gap: 12px;
            padding: 12px 0;
            border-top: 1px solid rgba(255,255,255,.04);
        }
        .fear-greed-snapshot-row:first-child {
            border-top: none;
        }
        .fear-greed-snapshot-label {
            font-size: .75rem;
            color: #8f8f8f;
            margin-bottom: 2px;
        }
        .fear-greed-snapshot-rating {
            font-size: .78rem;
            color: #fff;
            font-weight: 700;
            line-height: 1.2;
        }
        .fear-greed-snapshot-badge {
            min-width: 42px;
            height: 42px;
            border-radius: 999px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-family: 'Source Code Pro', monospace;
            font-size: .95rem;
            font-weight: 700;
            color: #1f1f1f;
            background: #e7c08d;
            border: 1px solid rgba(201,168,76,.8);
            box-shadow: inset 0 0 0 1px rgba(0,0,0,.08);
        }
        .fear-greed-value {
            font-family: 'Source Code Pro', monospace;
            font-size: 3rem;
            font-weight: 600;
            color: var(--gold-light);
            line-height: 1;
        }
        .fear-greed-rating {
            font-size: .95rem;
            color: #fff;
            font-weight: 600;
        }
        .fear-greed-meta {
            font-size: .75rem;
            color: var(--text-dim);
            font-family: 'Source Code Pro', monospace;
        }
        .fear-greed-chart-wrap {
            position: relative;
            height: 260px;
        }
        .fear-greed-right {
            display: grid;
            grid-template-rows: 260px auto;
            gap: 18px;
        }
        .fear-greed-gauge-wrap {
            border-top: 1px solid rgba(255,255,255,.06);
            padding-top: 10px;
            min-height: 320px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .fear-greed-gauge {
            width: 100%;
            max-width: 680px;
            aspect-ratio: 2 / 1.08;
            position: relative;
        }
        .fear-greed-gauge svg {
            width: 100%;
            height: auto;
            display: block;
        }
        .gauge-needle {
            transition: transform .6s ease;
        }
        .gauge-number {
            font-family: 'Source Code Pro', monospace;
            font-size: 46px;
            font-weight: 700;
            fill: #1f1f1f;
        }
        .gauge-tick-text {
            font-family: 'Source Code Pro', monospace;
            font-size: 16px;
            fill: #8a8a8a;
        }
        .gauge-label-text {
            font-family: 'Noto Sans TC', sans-serif;
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 1px;
            fill: #6d6d6d;
        }
        .gauge-dot {
            fill: #8a8a8a;
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
            height: 480px;
            margin-top: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
        }


        .macro-card-grid {
            display: grid;
            grid-template-columns: 220px 1fr;
            gap: 24px;
            align-items: stretch;
        }
        .macro-value-panel {
            border-right: 1px solid var(--border);
            padding-right: 20px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 10px;
        }
        .macro-value-number {
            font-family: 'Source Code Pro', monospace;
            font-size: 3rem;
            line-height: 1;
            color: var(--gold-light);
            font-weight: 700;
        }
        .macro-value-label {
            color: #fff;
            font-size: 1rem;
            font-weight: 600;
        }
        .macro-meta {
            font-family: 'Source Code Pro', monospace;
            font-size: .78rem;
            color: var(--text-dim);
        }
        .macro-detail-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 14px;
        }
        .macro-detail-item {
            background: linear-gradient(180deg, #121212, #0f0f0f);
            border: 1px solid rgba(255,255,255,.06);
            border-radius: 6px;
            padding: 16px;
            min-height: 110px;
        }
        .macro-detail-label {
            font-size: .7rem;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            color: var(--text-dim);
            margin-bottom: 10px;
        }
        .macro-detail-value {
            font-family: 'Source Code Pro', monospace;
            color: #fff;
            font-size: 1.2rem;
            font-weight: 700;
            margin-bottom: 8px;
        }
        .macro-note {
            margin-top: 14px;
            font-size: .75rem;
            color: var(--text-dim);
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
            .full-width-card { padding: 24px 20px; }
            .fear-greed-grid { grid-template-columns: 1fr; }
            .fear-greed-score { border-right: none; padding-right: 0; border-bottom: 1px solid var(--border); padding-bottom: 16px; }
            .macro-card-grid { grid-template-columns: 1fr; }
            .macro-value-panel { border-right: none; border-bottom: 1px solid var(--border); padding-right: 0; padding-bottom: 16px; }
            .macro-detail-grid { grid-template-columns: 1fr 1fr; }
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
    '不要投資於你不了解的事物。',
    '建立良好的聲譽需要 20 年，但要毀掉它只需要 5 分鐘。',
    '我們不必比別人聰明，我們只需要比別人更有紀律。',
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

        <div class="stat-row">
            <div>
                <div class="stat-name" title="投資組合今年以來（從年初至今）的實際累積報酬率" style="cursor: help; border-bottom: 1px dotted var(--text-dim); display: inline-block;">持倉 YTD 報酬</div>
            </div>
            <div style="text-align:right">
                <div class="stat-value {% if port_ytd_ret != 'N/A' and '-' not in port_ytd_ret %}gain{% elif port_ytd_ret != 'N/A' %}loss{% endif %}">{{ port_ytd_ret }}</div>
                <div class="stat-sub">Portfolio (YTD)</div>
            </div>
        </div>

        <div class="stat-row">
            <div>
                <div class="stat-name" title="S&amp;P 500 今年以來（從年初至今）的實際累積報酬率" style="cursor: help; border-bottom: 1px dotted var(--text-dim); display: inline-block;">大盤 YTD 報酬</div>
            </div>
            <div style="text-align:right">
                <div class="stat-value {% if port_sp500_ret != 'N/A' and '-' not in port_sp500_ret %}gain{% elif port_sp500_ret != 'N/A' %}loss{% endif %}">{{ port_sp500_ret }}</div>
                <div class="stat-sub">S&amp;P 500 (YTD)</div>
            </div>
        </div>

        <div class="stat-row">
            <div>
                <div class="stat-name" title="Sharpe Ratio = (預期報酬率 - 無風險利率估值) / 投資組合標準差 (每日變動值年化)" style="cursor: help; border-bottom: 1px dotted var(--text-dim); display: inline-block;">Sharpe Ratio</div>
            </div>
            <div style="text-align:right">
                <div class="stat-value">{{ port_sharpe }}</div>
                <div class="stat-sub">YTD Daily</div>
            </div>
        </div>

        <div class="stat-row">
            <div>
                <div class="stat-name" title="Beta = Cov(投資組合報酬, 大盤報酬) / Var(大盤報酬)" style="cursor: help; border-bottom: 1px dotted var(--text-dim); display: inline-block;">Beta</div>
            </div>
            <div style="text-align:right">
                <div class="stat-value">{{ port_beta }}</div>
                <div class="stat-sub">vs S&amp;P 500</div>
            </div>
        </div>

        <div class="stat-row">
            <div>
                <div class="stat-name" title="Alpha = 投資組合實際 YTD 報酬 - [無風險基準 + Beta × (大盤 YTD 報酬 - 無風險基準)]" style="cursor: help; border-bottom: 1px dotted var(--text-dim); display: inline-block;">Alpha</div>
            </div>
            <div style="text-align:right">
                <div class="stat-value {% if port_alpha != 'N/A' and '-' not in port_alpha %}gain{% elif port_alpha != 'N/A' %}loss{% endif %}">{{ port_alpha }}</div>
                <div class="stat-sub">YTD</div>
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

<div class="full-width-card">
    <div class="chart-label" style="display: flex; justify-content: space-between; align-items: center;">
        <span>CNN Fear & Greed Index · 市場情緒</span>
        <a href="https://edition.cnn.com/markets/fear-and-greed" target="_blank" rel="noopener" style="font-size: 0.75rem; font-weight: 500; color: var(--gold-light); text-decoration: none; padding-bottom: 2px;">Data Source ↗</a>
    </div>
    <div class="fear-greed-grid">
        <div class="fear-greed-score">
            <div class="fear-greed-snapshot-table">
                <div class="fear-greed-snapshot-row">
                    <div>
                        <div class="fear-greed-snapshot-label">Previous close</div>
                        <div class="fear-greed-snapshot-rating">{{ fear_greed_prev_rating }}</div>
                    </div>
                    <div class="fear-greed-snapshot-badge">{{ fear_greed_prev_str }}</div>
                </div>
                <div class="fear-greed-snapshot-row">
                    <div>
                        <div class="fear-greed-snapshot-label">1 week ago</div>
                        <div class="fear-greed-snapshot-rating">{{ fear_greed_week_rating }}</div>
                    </div>
                    <div class="fear-greed-snapshot-badge">{{ fear_greed_week_score_str }}</div>
                </div>
                <div class="fear-greed-snapshot-row">
                    <div>
                        <div class="fear-greed-snapshot-label">1 month ago</div>
                        <div class="fear-greed-snapshot-rating">{{ fear_greed_month_rating }}</div>
                    </div>
                    <div class="fear-greed-snapshot-badge">{{ fear_greed_month_score_str }}</div>
                </div>
                <div class="fear-greed-snapshot-row">
                    <div>
                        <div class="fear-greed-snapshot-label">1 year ago</div>
                        <div class="fear-greed-snapshot-rating">{{ fear_greed_year_rating }}</div>
                    </div>
                    <div class="fear-greed-snapshot-badge">{{ fear_greed_year_score_str }}</div>
                </div>
            </div>
            <div class="fear-greed-value">{{ fear_greed_score_str }}</div>
            <div class="fear-greed-rating">{{ fear_greed_rating }}</div>
            <div class="fear-greed-meta">前一日：{{ fear_greed_prev_str }}</div>
            <div class="fear-greed-meta">日變動：
                <span class="{% if fear_greed_delta is not none and fear_greed_delta > 0 %}gain-cell{% elif fear_greed_delta is not none and fear_greed_delta < 0 %}loss-cell{% endif %}">
                    {{ fear_greed_delta_str }}
                </span>
            </div>
            <div class="fear-greed-meta">區間：0–24 極度恐懼 · 25–44 恐懼 · 45–55 中性 · 56–74 貪婪 · 75–100 極度貪婪</div>
        </div>
        <div class="fear-greed-right">
            <div class="fear-greed-chart-wrap">
                <canvas id="fearGreedChart"></canvas>
            </div>
            <div class="fear-greed-gauge-wrap">
                <div class="fear-greed-gauge">
                    <svg viewBox="0 0 640 340" aria-label="CNN Fear and Greed Gauge">
                        <path id="fg-sector-0" d="M38 300 A282 282 0 0 1 121.59 100.51 L175.63 154.55 A205.58 205.58 0 0 0 114.42 300 Z" fill="#e8e8e8"/>
                        <path id="fg-sector-1" d="M125.83 96.42 A282 282 0 0 1 254.96 26.09 L270.57 100.48 A205.58 205.58 0 0 0 179.67 149.97 Z" fill="#e4e4e4"/>
                        <path id="fg-sector-2" d="M259.83 25.09 A282 282 0 0 1 380.17 25.09 L364.56 99.48 A205.58 205.58 0 0 0 275.44 99.48 Z" fill="#dddddd"/>
                        <path id="fg-sector-3" d="M385.04 26.09 A282 282 0 0 1 514.17 96.42 L460.33 149.97 A205.58 205.58 0 0 0 369.43 100.48 Z" fill="#e4e4e4"/>
                        <path id="fg-sector-4" d="M518.41 100.51 A282 282 0 0 1 602 300 L525.58 300 A205.58 205.58 0 0 0 464.37 154.55 Z" fill="#e8e8e8"/>

                        <path d="M114.42 300 A205.58 205.58 0 0 1 525.58 300" fill="none" stroke="#dedede" stroke-width="76" stroke-linecap="butt"/>

                        <text x="175" y="92" class="gauge-label-text" transform="rotate(-33 175 92)">FEAR</text>
                        <text x="282" y="52" class="gauge-label-text">NEUTRAL</text>
                        <text x="422" y="92" class="gauge-label-text" transform="rotate(33 422 92)">GREED</text>
                        <text x="70" y="246" class="gauge-label-text" transform="rotate(-63 70 246)">EXTREME</text>
                        <text x="76" y="274" class="gauge-label-text" transform="rotate(-63 76 274)">FEAR</text>
                        <text x="560" y="246" class="gauge-label-text" transform="rotate(63 560 246)">EXTREME</text>
                        <text x="564" y="274" class="gauge-label-text" transform="rotate(63 564 274)">GREED</text>

                        <text x="145" y="184" class="gauge-tick-text">25</text>
                        <text x="300" y="132" class="gauge-tick-text">50</text>
                        <text x="445" y="184" class="gauge-tick-text">75</text>
                        <text x="112" y="297" class="gauge-tick-text">0</text>
                        <text x="488" y="297" class="gauge-tick-text">100</text>

                        <circle cx="320" cy="300" r="58" fill="#e7e7e7"/>
                        <text id="fearGreedGaugeScore" x="320" y="340" text-anchor="middle" class="gauge-number">{{ fear_greed_score_str }}</text>

                        <g id="fearGreedNeedle" class="gauge-needle">
                            <rect x="128" y="294" width="192" height="12" fill="#1f1f1f" rx="2" ry="2"/>
                            <path d="M128 286 L86 300 L128 314 Z" fill="#1f1f1f"/>
                        </g>
                    </svg>
                </div>
            </div>
        </div>
    </div>
</div>


<div class="full-width-card" style="padding: 24px 40px;">
    <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 16px;">
        <div>
            <div class="chart-label" style="border: none; padding: 0; margin: 0 0 8px 0;">S&amp;P 500 Trailing P/E · 實際本益比 (近12個月)</div>
            <div class="macro-meta">資料日期：{{ sp500_fpe_date }} · 來源：<a href="{{ sp500_fpe_source_url }}" target="_blank" rel="noopener" style="color: var(--gold-light); text-decoration:none;">{{ sp500_fpe_source_name }}</a></div>
        </div>
        <div style="display: flex; gap: 32px; align-items: baseline;">
            <div>
                <span class="macro-meta">Latest: </span>
                <span style="font-family: 'Source Code Pro', monospace; font-size: 1.4rem; color: var(--gold-light); font-weight: 700;">{{ sp500_fpe_value_str }}</span>
                <span class="macro-meta" style="margin-left: 4px;">({{ sp500_fpe_valuation }})</span>
            </div>
            <div>
                <span class="macro-meta">Previous: </span>
                <span style="font-family: 'Source Code Pro', monospace; font-size: 1.1rem; color: #fff;">{{ sp500_fpe_prev_value_str }}</span>
            </div>
            <div>
                <span class="macro-meta">Delta: </span>
                <span class="{% if sp500_fpe_delta is not none and sp500_fpe_delta > 0 %}gain-cell{% elif sp500_fpe_delta is not none and sp500_fpe_delta < 0 %}loss-cell{% endif %}" style="font-family: 'Source Code Pro', monospace; font-size: 1.1rem; font-weight: 600;">{{ sp500_fpe_delta_str }}</span>
            </div>
        </div>
    </div>
</div>

<div class="full-width-card" style="margin-top: 24px; padding: 28px 40px;">
    <div class="chart-label">S&amp;P 500 Technical Trend · 大盤均線技術面</div>
    <div style="display: grid; grid-template-columns: minmax(260px, 1fr) 2fr; gap: 40px; align-items: stretch;">
        <div>
            <div style="font-size: 2.2rem; color: #fff; font-family: 'Source Code Pro', monospace; font-weight: 700; line-height: 1.2;">
                {{ sp5_price }}
            </div>
            <div style="font-size: 0.8rem; color: var(--text-dim); margin-bottom: 24px;">S&P 500 Current Price</div>
            
            <ul style="list-style: none; padding: 0; margin: 0; font-size: 0.85rem; color: #ccc;">
                <li style="margin-bottom: 16px; display: flex; align-items: center; justify-content: space-between; padding-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.06);">
                    <div>月線 (20MA) 
                        {% if sp5_b20 %}
                        <span style="color: var(--red); font-size: 0.7rem; background: var(--red-dim); padding: 2px 6px; border-radius: 4px; margin-left: 6px;">跌破</span>
                        {% else %}
                        <span style="color: var(--green); font-size: 0.7rem; background: var(--green-dim); padding: 2px 6px; border-radius: 4px; margin-left: 6px;">有守</span>
                        {% endif %}
                    </div>
                    <div style="font-family: 'Source Code Pro', monospace; color: var(--gold-light);">{{ sp5_ma20 }}</div>
                </li>
                <li style="margin-bottom: 16px; display: flex; align-items: center; justify-content: space-between; padding-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.06);">
                    <div>季線 (60MA) 
                        {% if sp5_b60 %}
                        <span style="color: var(--red); font-size: 0.7rem; background: var(--red-dim); padding: 2px 6px; border-radius: 4px; margin-left: 6px;">跌破</span>
                        {% else %}
                        <span style="color: var(--green); font-size: 0.7rem; background: var(--green-dim); padding: 2px 6px; border-radius: 4px; margin-left: 6px;">有守</span>
                        {% endif %}
                    </div>
                    <div style="font-family: 'Source Code Pro', monospace; color: var(--gold-light);">{{ sp5_ma60 }}</div>
                </li>
                <li style="margin-bottom: 16px; display: flex; align-items: center; justify-content: space-between; padding-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.06);">
                    <div>年線 (250MA) 
                        {% if sp5_b250 %}
                        <span style="color: var(--red); font-size: 0.7rem; background: var(--red-dim); padding: 2px 6px; border-radius: 4px; margin-left: 6px;">跌破</span>
                        {% else %}
                        <span style="color: var(--green); font-size: 0.7rem; background: var(--green-dim); padding: 2px 6px; border-radius: 4px; margin-left: 6px;">有守</span>
                        {% endif %}
                    </div>
                    <div style="font-family: 'Source Code Pro', monospace; color: var(--gold-light);">{{ sp5_ma250 }}</div>
                </li>
                <li style="margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between;">
                    <div>五年線 (1250MA) 
                        {% if sp5_b1250 %}
                        <span style="color: var(--red); font-size: 0.7rem; background: var(--red-dim); padding: 2px 6px; border-radius: 4px; margin-left: 6px;">跌破</span>
                        {% else %}
                        <span style="color: var(--green); font-size: 0.7rem; background: var(--green-dim); padding: 2px 6px; border-radius: 4px; margin-left: 6px;">有守</span>
                        {% endif %}
                    </div>
                    <div style="font-family: 'Source Code Pro', monospace; color: var(--gold-light);">{{ sp5_ma1250 }}</div>
                </li>
            </ul>
        </div>
        <div style="position: relative; min-height: 250px;">
            <canvas id="sp500HistChart"></canvas>
        </div>
    </div>
</div>

<div class="full-width-card" style="margin-top: 24px; padding: 28px 40px;">
    <div class="chart-label">Contrarian Bottom-Fishing Signals · 抄底策略指標</div>
    <div style="font-size: .75rem; color: var(--text-dim); margin-bottom: 24px;">
        當市場極度恐慌、融資退場、選擇權避險情緒高漲時，往往是相對低點。本區指標皆為反向指標。
    </div>

    <!-- 抄底訊號判定區域 -->
    <div style="margin-bottom: 24px; padding: 20px; background: linear-gradient(135deg, rgba(201,168,76,0.05), rgba(0,0,0,0)); border: 1px solid rgba(201,168,76,0.3); border-radius: 6px;">
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 24px;">
            <!-- B 級 -->
            <div>
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
                    <div style="font-size: 1.1rem; color: var(--gold-light); font-weight: 700; display: flex; align-items: center; gap: 8px;">
                        B 級訊號：開始分批抄底
                        {% if b_class_signal %}
                            <span style="background: var(--green); color: #000; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700;">達成</span>
                        {% endif %}
                    </div>
                    <div style="font-size: 0.85rem; color: var(--text-dim);">符合條件：<span style="color: #fff; font-weight: 700;">{{ b_conds_met }} / 6 (需滿4項)</span></div>
                </div>
                <div style="font-size: 0.75rem; color: var(--text-dim); margin-bottom: 12px;">先打 10%~20% 現金</div>
                <ul style="list-style: none; padding: 0; margin: 0; font-size: 0.85rem; color: #ccc;">
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if b_cond_sp500 %}var(--green){% else %}var(--text-dim){% endif %};">{% if b_cond_sp500 %}●{% else %}○{% endif %}</span> 
                        S&amp;P 500 距前高跌 10% 以上 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ sp500_dd_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if b_cond_vix %}var(--green){% else %}var(--text-dim){% endif %};">{% if b_cond_vix %}●{% else %}○{% endif %}</span> 
                        VIX &gt; 30 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ vix_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if b_cond_pcr %}var(--green){% else %}var(--text-dim){% endif %};">{% if b_cond_pcr %}●{% else %}○{% endif %}</span> 
                        Put/Call Ratio &gt; 0.9 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ pcr_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if b_cond_finra %}var(--green){% else %}var(--text-dim){% endif %};">{% if b_cond_finra %}●{% else %}○{% endif %}</span> 
                        FINRA 融資餘額轉弱 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ finra_mom_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if b_cond_fg %}var(--green){% else %}var(--text-dim){% endif %};">{% if b_cond_fg %}●{% else %}○{% endif %}</span> 
                        CNN Fear &amp; Greed &lt; 15 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ fear_greed_score_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if b_cond_ma60 %}var(--green){% else %}var(--text-dim){% endif %};">{% if b_cond_ma60 %}●{% else %}○{% endif %}</span> 
                        S&amp;P 500 跌破季線 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({% if b_cond_ma60 %}跌破{% else %}未破{% endif %})</span>
                    </li>
                </ul>
            </div>
            <!-- A 級 -->
            <div>
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
                    <div style="font-size: 1.1rem; color: var(--gold-light); font-weight: 700; display: flex; align-items: center; gap: 8px;">
                        A 級訊號：可以大量抄底
                        {% if a_class_signal %}
                            <span style="background: var(--green); color: #000; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700;">達成</span>
                        {% endif %}
                    </div>
                    <div style="font-size: 0.85rem; color: var(--text-dim);">符合條件：<span style="color: #fff; font-weight: 700;">{{ a_conds_met }} / 7 (需滿5項)</span></div>
                </div>
                <div style="font-size: 0.75rem; color: var(--text-dim); margin-bottom: 12px;">先打 20%~40% 現金</div>
                <ul style="list-style: none; padding: 0; margin: 0; font-size: 0.85rem; color: #ccc;">
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if a_cond_sp500 %}var(--green){% else %}var(--text-dim){% endif %};">{% if a_cond_sp500 %}●{% else %}○{% endif %}</span> 
                        S&amp;P 500 跌 15%~20% <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ sp500_dd_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if a_cond_vix %}var(--green){% else %}var(--text-dim){% endif %};">{% if a_cond_vix %}●{% else %}○{% endif %}</span> 
                        VIX &gt; 35 或 40 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ vix_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if a_cond_pcr %}var(--green){% else %}var(--text-dim){% endif %};">{% if a_cond_pcr %}●{% else %}○{% endif %}</span> 
                        Put/Call Ratio &gt; 1.0 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ pcr_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if a_cond_finra_cont %}var(--green){% else %}var(--text-dim){% endif %};">{% if a_cond_finra_cont %}●{% else %}○{% endif %}</span> 
                        FINRA 融資餘額連續下滑 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ finra_mom_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if a_cond_pe %}var(--green){% else %}var(--text-dim){% endif %};">{% if a_cond_pe %}●{% else %}○{% endif %}</span> 
                        S&amp;P 500 Trailing P/E &lt; 25 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ sp500_fpe_value_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if a_cond_fg %}var(--green){% else %}var(--text-dim){% endif %};">{% if a_cond_fg %}●{% else %}○{% endif %}</span> 
                        CNN Fear &amp; Greed &lt; 10 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ fear_greed_score_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if a_cond_ma250 %}var(--green){% else %}var(--text-dim){% endif %};">{% if a_cond_ma250 %}●{% else %}○{% endif %}</span> 
                        S&amp;P 500 跌破年線 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({% if a_cond_ma250 %}跌破{% else %}未破{% endif %})</span>
                    </li>
                </ul>
            </div>
            <!-- S 級 -->
            <div>
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
                    <div style="font-size: 1.1rem; color: var(--gold-light); font-weight: 700; display: flex; align-items: center; gap: 8px;">
                        S 級訊號：極端底部
                        {% if s_class_signal %}
                            <span style="background: var(--green); color: #000; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700;">強烈達成</span>
                        {% endif %}
                    </div>
                    <div style="font-size: 0.85rem; color: var(--text-dim);">符合條件：<span style="color: #fff; font-weight: 700;">{{ s_conds_met }} / 7 (需滿5項)</span></div>
                </div>
                <div style="font-size: 0.75rem; color: var(--text-dim); margin-bottom: 12px;">全面建倉 / 重壓</div>
                <ul style="list-style: none; padding: 0; margin: 0; font-size: 0.85rem; color: #ccc;">
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if s_cond_sp500 %}var(--green){% else %}var(--text-dim){% endif %};">{% if s_cond_sp500 %}●{% else %}○{% endif %}</span> 
                        S&amp;P 500 跌 20% <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ sp500_dd_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if s_cond_vix %}var(--green){% else %}var(--text-dim){% endif %};">{% if s_cond_vix %}●{% else %}○{% endif %}</span> 
                        VIX &gt; 35 或 40 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ vix_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if s_cond_pcr %}var(--green){% else %}var(--text-dim){% endif %};">{% if s_cond_pcr %}●{% else %}○{% endif %}</span> 
                        Put/Call Ratio &gt; 1.0 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ pcr_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if s_cond_finra_cont %}var(--green){% else %}var(--text-dim){% endif %};">{% if s_cond_finra_cont %}●{% else %}○{% endif %}</span> 
                        FINRA 融資餘額連續下滑 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ finra_mom_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if s_cond_pe %}var(--green){% else %}var(--text-dim){% endif %};">{% if s_cond_pe %}●{% else %}○{% endif %}</span> 
                        S&amp;P 500 Trailing P/E &lt; 15 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ sp500_fpe_value_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if s_cond_fg %}var(--green){% else %}var(--text-dim){% endif %};">{% if s_cond_fg %}●{% else %}○{% endif %}</span> 
                        CNN Fear &amp; Greed &lt; 5 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ fear_greed_score_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if s_cond_ma1250 %}var(--green){% else %}var(--text-dim){% endif %};">{% if s_cond_ma1250 %}●{% else %}○{% endif %}</span> 
                        S&amp;P 500 跌破五年線 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({% if s_cond_ma1250 %}跌破{% else %}未破{% endif %})</span>
                    </li>
                </ul>
            </div>
            <!-- SS 級 -->
            <div>
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
                    <div style="font-size: 1.1rem; color: #ff4d4d; font-weight: 700; display: flex; align-items: center; gap: 8px;">
                        SS 級訊號：史詩大底
                        {% if ss_class_signal %}
                            <span style="background: var(--red); color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700;">財富重分配</span>
                        {% endif %}
                    </div>
                    <div style="font-size: 0.85rem; color: var(--text-dim);">符合條件：<span style="color: #fff; font-weight: 700;">{{ ss_conds_met }} / 5 (需滿4項)</span></div>
                </div>
                <div style="font-size: 0.75rem; color: var(--text-dim); margin-bottom: 12px;">信貸ALL IN / 破產或暴富</div>
                <ul style="list-style: none; padding: 0; margin: 0; font-size: 0.85rem; color: #ccc;">
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if ss_cond_sp500 %}var(--red){% else %}var(--text-dim){% endif %};">{% if ss_cond_sp500 %}●{% else %}○{% endif %}</span> 
                        S&amp;P 500 跌 30% <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ sp500_dd_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if ss_cond_vix %}var(--red){% else %}var(--text-dim){% endif %};">{% if ss_cond_vix %}●{% else %}○{% endif %}</span> 
                        VIX &gt; 40 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ vix_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if ss_cond_pcr %}var(--red){% else %}var(--text-dim){% endif %};">{% if ss_cond_pcr %}●{% else %}○{% endif %}</span> 
                        Put/Call Ratio &gt; 1.2 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ pcr_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if ss_cond_shiller %}var(--red){% else %}var(--text-dim){% endif %};">{% if ss_cond_shiller %}●{% else %}○{% endif %}</span> 
                        Shiller P/E &lt; 20 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({{ shiller_pe_value_str }})</span>
                    </li>
                    <li style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                        <span style="color: {% if ss_cond_ma1250 %}var(--red){% else %}var(--text-dim){% endif %};">{% if ss_cond_ma1250 %}●{% else %}○{% endif %}</span> 
                        S&amp;P 500 跌破五年線 <span style="color: var(--text-dim); font-family: 'Source Code Pro', monospace;">({% if ss_cond_ma1250 %}跌破{% else %}未破{% endif %})</span>
                    </li>
                </ul>
            </div>
        </div>
    </div>
    
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 24px;">
        
        <!-- FINRA Margin -->
        <div style="background: linear-gradient(180deg, #121212, #0f0f0f); border: 1px solid rgba(255,255,255,.06); border-radius: 6px; padding: 20px;">
            <div style="font-size: .7rem; letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-dim); margin-bottom: 12px;">FINRA Margin Debt</div>
            <div style="font-size: 1.6rem; color: #fff; font-family: 'Source Code Pro', monospace; font-weight: 700; margin-bottom: 6px;">
                {{ finra_val_str }} <span style="font-size: 0.8rem; color: var(--text-dim); font-weight: 400;">百萬 USD</span>
            </div>
            <div style="font-family: 'Source Code Pro', monospace; font-size: .78rem; margin-bottom: 16px;">MoM: <span class="{% if finra_mom is not none and finra_mom > 0 %}gain-cell{% elif finra_mom is not none and finra_mom < 0 %}loss-cell{% endif %}">{{ finra_mom_str }}</span></div>
            <div style="font-size: .75rem; color: #999; line-height: 1.6;">
                <strong>策略含義：</strong>代表美股融資(槓桿)餘額。當市場大跌且融資餘額<b>大幅快速下降(斷頭)</b>時，代表籌碼洗淨，有利於底部形成。
            </div>
            <div style="font-family: 'Source Code Pro', monospace; font-size: .7rem; color: var(--text-dim); margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,.04);">資料月份：{{ finra_month }}</div>
        </div>

        <!-- Cboe VIX -->
        <div style="background: linear-gradient(180deg, #121212, #0f0f0f); border: 1px solid rgba(255,255,255,.06); border-radius: 6px; padding: 20px;">
            <div style="font-size: .7rem; letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-dim); margin-bottom: 12px;">CBOE Volatility Index (VIX)</div>
            <div style="font-size: 1.8rem; color: {% if vix is not none and vix >= 30 %}var(--green){% else %}#fff{% endif %}; font-family: 'Source Code Pro', monospace; font-weight: 700; margin-bottom: 16px;">
                {{ vix_str }}
            </div>
            <div style="font-size: .75rem; color: #999; line-height: 1.6;">
                <strong>策略含義：</strong>衡量標普500期權的隱含波動率。VIX > 30 常為恐慌；若 VIX > 40，則歷史上極高機率為短期或中長期大底，為<b>強烈抄底訊號</b>。
            </div>
        </div>

        <!-- Put/Call Ratio -->
        <div style="background: linear-gradient(180deg, #121212, #0f0f0f); border: 1px solid rgba(255,255,255,.06); border-radius: 6px; padding: 20px;">
            <div style="font-size: .7rem; letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-dim); margin-bottom: 12px;">Put / Call Ratio</div>
            <div style="font-size: 1.8rem; color: {% if pcr is not none and pcr >= 1.0 %}var(--green){% else %}#fff{% endif %}; font-family: 'Source Code Pro', monospace; font-weight: 700; margin-bottom: 16px;">
                {{ pcr_str }}
            </div>
            <div style="font-size: .75rem; color: #999; line-height: 1.6;">
                <strong>策略含義：</strong>當數值 > 1.0 (甚至 > 1.2) 時，說明整個期權市場瘋狂買保險(看跌)，極度悲觀往往是歷史回測最佳的<b>反向作多時機</b>。
            </div>
        </div>

        <!-- Shiller P/E -->
        <div style="background: linear-gradient(180deg, #121212, #0f0f0f); border: 1px solid rgba(255,255,255,.06); border-radius: 6px; padding: 20px;">
            <div style="font-size: .7rem; letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-dim); margin-bottom: 12px;">Shiller P/E (CAPE)</div>
            <div style="font-size: 1.8rem; color: #fff; font-family: 'Source Code Pro', monospace; font-weight: 700; margin-bottom: 6px;">
                {{ shiller_pe_value_str }} <span style="font-size: 0.8rem; color: var(--text-dim); font-weight: 400;">({{ shiller_pe_valuation }})</span>
            </div>
            <div style="font-size: .75rem; color: #999; line-height: 1.6; margin-top: 16px;">
                <strong>策略含義：</strong>席勒本益比，排除了景氣循環週期的雜訊，代表大長期的估值基準。<30為非泡沫，若 <b><20 為十年難見買點</b>。
            </div>
        </div>

    </div>
</div>

<!-- PORTFOLIO COMPOSITION -->
<div class="table-section" style="border-bottom: 1px solid rgba(255,255,255,0.05); margin-bottom: 6px; padding-bottom: 20px;">
    <div class="table-header">Portfolio Composition · 持股組成</div>
    <div id="compositionBar" style="height:7px;border-radius:4px;overflow:hidden;display:flex;gap:1px;background:#181818;margin-bottom:14px;"></div>
    <div id="compositionBadges" style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:14px;">
        <span style="font-size:.75rem;color:var(--text-dim);">Loading…</span>
    </div>
    <div style="font-size:.75rem;color:#888;line-height:1.75;">
        <strong style="color:#bbb;">策略摘要：</strong>
        科技成長（GOOGL、NVDA、MSFT、TSM、SNPS、AMZN、MU）為核心，搭配防禦消費（KO、MCD、YUM、DPZ、UNH）+ 公用事業（AEP、DUK）作為大跌時的護城層。清潔能源（CEG、FSLR）對應 AI 電力需求長期主題，核能（LEU）適居去碳化潮流。
    </div>
</div>

<!-- TABLE -->
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
                    <th>高點回檔 (1Y)</th>
                    <th>Trailing P/E</th>
                    <th>Forward P/E</th>
                    <th>年線狀態</th>
                    <th>報酬率</th>
                </tr>
            </thead>
            <tbody id="holdingsTbody">
                {% for it in core_items %}
                <tr>
                    <td title="Trailing PE: {{ it.tpe_str }}&#10;Forward PE: {{ it.fpe_str }}" style="cursor: help;">
                        <span class="rank {% if loop.index <= 3 %}top{% endif %}">{{ loop.index }}</span>
                        {{ it.symbol }}
                    </td>
                    <td>{{ it.price_str }}</td>
                    <td>{{ it.cost_str }}</td>
                    <td>{{ it.shares_str }}</td>
                    <td>{{ it.mv_str }}</td>
                    <td>
                        <span class="{% if it.dd_str != 'N/A' and '-' in it.dd_str %}loss-cell{% endif %}">
                            {{ it.dd_str }}
                        </span>
                    </td>
                    <td>{{ it.tpe_str }}</td>
                    <td>{{ it.fpe_str }}</td>
                    <td>
                        {% if it.broken_250 %}
                        <span style="color:var(--red); font-size:0.75rem; background:var(--red-dim); padding:2px 6px; border-radius:4px;">跌破</span>
                        {% else %}
                        <span style="color:var(--green); font-size:0.75rem; background:var(--green-dim); padding:2px 6px; border-radius:4px;">站上</span>
                        {% endif %}
                    </td>
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

<!-- WATCHLIST -->
<div class="table-section" style="margin-bottom: 40px;">
    <div class="table-header">Watchlist Alerts · 觀察名單預警</div>
    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>代號 Symbol</th>
                    <th>現價</th>
                    <th>高點回檔 (1Y)</th>
                    <th>Trailing P/E</th>
                    <th>Forward P/E</th>
                    <th>預警訊號</th>
                </tr>
            </thead>
            <tbody>
                {% for w in watchlist_items %}
                <tr>
                    <td>{{ w.symbol }}</td>
                    <td>{{ w.price_str }}</td>
                    <td>
                        <span class="{% if w.dd_str != 'N/A' and '-' in w.dd_str %}loss-cell{% endif %}">
                            {{ w.dd_str }}
                        </span>
                    </td>
                    <td>{{ w.tpe_str }}</td>
                    <td>{{ w.fpe_str }}</td>
                    <td style="text-align: right;">
                        {% if w.is_alert %}
                            {% for a in w.alerts %}
                                <span style="display:inline-block; margin-left:6px; font-size:0.7rem; background:var(--red); color:#fff; padding:2px 6px; border-radius:4px; font-family:'Noto Sans TC', sans-serif;">{{ a }}</span>
                            {% endfor %}
                        {% else %}
                            <span style="color:var(--text-dim); font-size:0.75rem;">正常</span>
                        {% endif %}
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
const fearGreedLabels = {{ fear_greed_chart_labels | safe }};
const fearGreedData = {{ fear_greed_chart_data | safe }};

const fgCtx = document.getElementById('fearGreedChart').getContext('2d');
new Chart(fgCtx, {
    type: 'line',
    data: {
        labels: fearGreedLabels,
        datasets: [{
            label: 'CNN Fear & Greed',
            data: fearGreedData,
            borderColor: '#c9a84c',
            backgroundColor: 'rgba(201, 168, 76, 0.12)',
            borderWidth: 2,
            fill: true,
            tension: 0.25,
            pointRadius: 0,
            pointHoverRadius: 3
        }]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: '#1a1a1a',
                borderColor: '#2a2a2a',
                borderWidth: 1,
                titleColor: '#ffffff',
                bodyColor: '#c9a84c'
            }
        },
        scales: {
            x: {
                ticks: { color: '#8a8a8a', maxTicksLimit: 8 },
                grid: { color: 'rgba(255,255,255,0.04)' }
            },
            y: {
                min: 0,
                max: 100,
                ticks: { color: '#8a8a8a', stepSize: 25 },
                grid: { color: 'rgba(255,255,255,0.06)' }
            }
        }
    }
});


const fgScoreRaw = {{ fear_greed_score if fear_greed_score is not none else 'null' }};
const fgNeedle = document.getElementById('fearGreedNeedle');
const fgGaugeScore = document.getElementById('fearGreedGaugeScore');

function clampFearGreedScore(v) {
    if (v === null || Number.isNaN(Number(v))) return null;
    return Math.max(0, Math.min(100, Number(v)));
}

function updateFearGreedGauge(score) {
    const clamped = clampFearGreedScore(score);
    if (clamped === null || !fgNeedle) return;
    const angle = (clamped / 100) * 180;
    fgNeedle.setAttribute('transform', `rotate(${angle} 320 300)`);
    if (fgGaugeScore) {
        fgGaugeScore.textContent = Math.round(clamped).toString();
    }
    
    const fills = ['#eab0a8', '#f2c7a6', '#e8d18d', '#a1d99b', '#74c476'];
    const strokes = ['#b11235', '#d35400', '#c39d2e', '#31a354', '#006d2c'];
    const bgFills = ['#e8e8e8', '#e4e4e4', '#dddddd', '#e4e4e4', '#e8e8e8'];
    
    let activeIdx = -1;
    if(clamped <= 24) activeIdx = 0;
    else if(clamped <= 44) activeIdx = 1;
    else if(clamped <= 55) activeIdx = 2;
    else if(clamped <= 74) activeIdx = 3;
    else activeIdx = 4;
    
    for(let i=0; i<5; i++) {
        const sec = document.getElementById('fg-sector-' + i);
        if(!sec) continue;
        if(i === activeIdx) {
            sec.setAttribute('fill', fills[i]);
            sec.setAttribute('stroke', strokes[i]);
            sec.setAttribute('stroke-width', '2');
        } else {
            sec.setAttribute('fill', bgFills[i]);
            sec.removeAttribute('stroke');
            sec.removeAttribute('stroke-width');
        }
    }
}

updateFearGreedGauge(fgScoreRaw);

const ctx = document.getElementById('holdingsChart').getContext('2d');
const chartLabels = {{ chart_labels | safe }};
const chartData   = {{ chart_data   | safe }};
const chartLogos  = {{ chart_logos  | safe }};

const GOLD_PALETTE = [
    '#4e9af1','#f16b4e','#4ecf8a','#b06cf7','#f7c24e',
    '#4ec8f7','#f74e8e','#7ecf4e','#f74e4e','#4e6ff7','#f7934e'
];

let chartObj = null;
const logoImages = {};
chartLogos.forEach((src, idx) => {
    if (src) {
        let img = new Image();
        img.src = src;
        img.onload = () => {
            if (chartObj) chartObj.update();
        };
        logoImages[idx] = img;
    }
});

const logoPlugin = {
    id: 'logoPlugin',
    afterDatasetDraw(chart, args, options) {
        const { ctx } = chart;
        const meta = chart.getDatasetMeta(0);
        meta.data.forEach((element, index) => {
            const img = logoImages[index];
            if (img && img.complete && img.naturalWidth !== 0) {
                const centerPoint = element.tooltipPosition();
                const x = centerPoint.x;
                const y = centerPoint.y;
                const size = 36;
                // Draw subtle white background circle for contrast
                ctx.save();
                ctx.beginPath();
                ctx.arc(x, y, size/2 + 1, 0, Math.PI * 2);
                ctx.fillStyle = 'rgba(255, 255, 255, 0.85)';
                ctx.fill();
                ctx.closePath();
                // Draw logo
                ctx.beginPath();
                ctx.arc(x, y, size/2, 0, Math.PI * 2);
                ctx.clip();
                ctx.drawImage(img, x - size/2, y - size/2, size, size);
                ctx.restore();
            }
        });
    }
};

chartObj = new Chart(ctx, {
    type: 'doughnut',
    plugins: [logoPlugin],
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
                position: 'bottom',
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

<script>
const sp5Labels = {{ sp5_chart_labels | safe }};
const sp5Data = {{ sp5_chart_points | safe }};
const sp5Ctx = document.getElementById('sp500HistChart').getContext('2d');

new Chart(sp5Ctx, {
    type: 'line',
    data: {
        labels: sp5Labels,
        datasets: [{
            label: 'S&P 500 (1Y)',
            data: sp5Data,
            borderColor: '#3ddc84',
            backgroundColor: 'rgba(61, 220, 132, 0.08)',
            borderWidth: 2,
            fill: true,
            tension: 0.1,
            pointRadius: 0,
            pointHoverRadius: 4
        }]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: '#1a1a1a',
                borderColor: '#2a2a2a',
                borderWidth: 1,
                titleColor: '#ffffff',
                bodyColor: '#3ddc84'
            }
        },
        scales: {
            x: {
                ticks: { color: '#8a8a8a', maxTicksLimit: 6 },
                grid: { color: 'rgba(255,255,255,0.04)' }
            },
            y: {
                ticks: { color: '#8a8a8a' },
                grid: { color: 'rgba(255,255,255,0.06)' }
            }
        }
    }
});

// Portfolio Composition Bar
(function(){
    const cats = {
        'GOOGL':'\u79d1\u6280\u6210\u9577','NVDA':'\u79d1\u6280\u6210\u9577','MSFT':'\u79d1\u6280\u6210\u9577','MU':'\u79d1\u6280\u6210\u9577',
        'SNPS':'科技成長','TSM':'科技成長','AMZN':'科技成長',
        'KO':'防禦消費','MCD':'防禦消費','YUM':'防禦消費','DPZ':'防禦消費','AXP':'防禦消費',
        'UNH':'醫療防禦',
        'AEP':'電力能源','DUK':'電力能源',
        'CEG':'電力能源','FSLR':'電力能源',
        'LEU':'電力能源',
        'ETN':'電力能源','HUBB':'電力能源',
    };
    const catColors = {
        '科技成長':'#4f9ef8','防禦消費':'#62d96b','電力能源':'#ffd700',
        '醫療防禦':'#b388ff','工業':'#a5a5a5',
    };
    const tbody = document.getElementById('holdingsTbody');
    if(!tbody) return;
    const rows = tbody.querySelectorAll('tr');
    const mvByCat = {};
    let totalMv = 0;
    rows.forEach(tr => {
        const tds = tr.querySelectorAll('td');
        if(tds.length < 5) return;
        const sym = tds[0].textContent.trim().replace(/^\d+\s*/, '');
        const mv = parseFloat(tds[4].textContent.replace(/,/g,''));
        if(isNaN(mv)) return;
        const cat = cats[sym] || '\u5176\u4ed6';
        mvByCat[cat] = (mvByCat[cat] || 0) + mv;
        totalMv += mv;
    });
    if(!totalMv) return;
    const sorted = Object.entries(mvByCat).sort((a,b)=>b[1]-a[1]);

    const bar = document.getElementById('compositionBar');
    if(bar) {
        bar.innerHTML = '';
        sorted.forEach(([cat, mv]) => {
            const pct = mv/totalMv*100;
            const color = catColors[cat]||'#888';
            const seg = document.createElement('div');
            seg.title = cat+': '+pct.toFixed(1)+'%';
            seg.style.cssText = 'height:100%;width:'+pct+'%;background:'+color+';';
            bar.appendChild(seg);
        });
    }
    const badges = document.getElementById('compositionBadges');
    if(badges) {
        badges.innerHTML = '';
        sorted.forEach(([cat, mv]) => {
            const pct = (mv/totalMv*100).toFixed(1);
            const color = catColors[cat]||'#888';
            const b = document.createElement('div');
            b.style.cssText = 'display:inline-flex;align-items:center;gap:8px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:6px;padding:8px 14px;';
            b.innerHTML = '<span style="width:8px;height:8px;border-radius:50%;background:'+color+';flex-shrink:0;"></span>'
                        + '<span style="font-size:.82rem;color:#ccc;">'+cat+'</span>'
                        + '<span style="font-size:.88rem;font-family:\'Source Code Pro\',monospace;color:'+color+';font-weight:700;">'+pct+'%</span>';
            badges.appendChild(b);
        });
    }
}());
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