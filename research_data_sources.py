"""Traceable financial fallbacks and reviewed company-disclosure supplements."""
from __future__ import annotations
import json
import logging
import math
import re
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

SUPPLEMENTS = Path(__file__).resolve().parent / 'data' / 'research_supplements.json'

def parse_scaled_number(value):
    match = re.fullmatch(r'\s*\$?\s*(-?[\d,]+(?:\.\d+)?)\s*([KMBT]?)\s*', value)
    if not match:
        return None
    result = float(match[1].replace(',', '')) * {'': 1, 'K': 1e3, 'M': 1e6, 'B': 1e9, 'T': 1e12}[match[2]]
    return result if math.isfinite(result) else None

def parse_stockanalysis_cashflow(html):
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text(' ', strip=True)
    # Statistics use the listed currency. Do not combine an unknown currency
    # with a USD market capitalization.
    if not re.search(r'(?:Real-Time|Delayed) Price\s*·\s*USD', text):
        return None
    rows = {}
    for row in soup.select('tr'):
        cells = row.select('td')
        if len(cells) == 2:
            rows[cells[0].get_text(' ', strip=True)] = cells[1].get_text(' ', strip=True)
    fcf = parse_scaled_number(rows.get('Free Cash Flow', ''))
    cap = parse_scaled_number(rows.get('Market Cap', ''))
    if fcf is None or cap is None or cap <= 0:
        return None
    updated = re.search(r'Last updated:\s*([A-Za-z]+ \d{1,2}, \d{4})', text)
    return {'free_cashflow': fcf, 'fcf_market_cap': cap, 'fcf_currency': 'USD',
            'source_updated': updated[1] if updated else '來源未提供更新日期'}

def fetch_cashflow_fallback(symbol):
    url = f'https://stockanalysis.com/stocks/{symbol.lower()}/statistics/'
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        result = parse_stockanalysis_cashflow(response.content)
        if result:
            result['fcf_source'] = {'label': 'Stock Analysis / S&P Global：FCF 與同源市值',
                                    'url': url, 'period': 'TTM；來源更新 ' + result.pop('source_updated'),
                                    'checked_at': datetime.now(timezone.utc).isoformat(),
                                    'note': '使用來源公布的四捨五入值；FCF = 營業現金流 − 資本支出，與 Yahoo levered FCF 定義可能不同。'}
        return result
    except (requests.RequestException, ValueError) as exc:
        logging.warning('Cash-flow fallback unavailable for %s: %s', symbol, exc)
        return None

def apply_reviewed_data(original, records=None):
    item = dict(original)
    if records is None:
        try:
            records = json.loads(SUPPLEMENTS.read_text(encoding='utf-8'))['companies']
        except (FileNotFoundError, ValueError, KeyError):
            records = {}
    record = records.get(item['symbol'], {})
    # Keep the reviewed disclosure visibly dated; never imply that it was
    # re-verified on each market quote refresh.
    if record.get('buyback'):
        item['reviewed_buyback'] = record['buyback']
        item['reviewed_source'] = record['source']
        item['reviewed_at'] = record['reviewed_at']
        latest_filed = item.get('buyback_program_filed') or ''
        item['reviewed_data_stale'] = latest_filed > record['source']['filed'] or (
            datetime.now(timezone.utc).date() - datetime.fromisoformat(record['reviewed_at']).date()
        ).days > 120
    statuses = dict(item.get('metric_status', {}))
    if item.get('trailing_pe') is None and item.get('trailing_eps') is not None and item['trailing_eps'] <= 0:
        statuses['trailing_pe'] = '不適用：近十二月 EPS 非正值'
        statuses['implied_eps_change'] = '不適用：缺少正值 TTM P/E'
    if item.get('roe') is None and item.get('book_value') is not None and item['book_value'] <= 0:
        statuses['roe'] = '不適用：股東權益非正值'
    item['metric_status'] = statuses
    return item
