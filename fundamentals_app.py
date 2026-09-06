# -*- coding: utf-8 -*-
"""Personal portfolio fundamentals dashboard.

The module serves the dashboard with Flask and can also generate a self-contained
GitHub Pages snapshot:

    python fundamentals_app.py --serve
    python fundamentals_app.py --output docs/index.html
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, send_file, send_from_directory
from pytz import timezone
from research_data_sources import apply_reviewed_data, fetch_cashflow_fallback


PROJECT_ROOT = Path(__file__).resolve().parent
SNAPSHOT_CACHE = PROJECT_ROOT / ".yf-cache" / "fundamentals_snapshot.json"
YFINANCE_CACHE = Path(
    os.environ.get(
        "YFINANCE_CACHE_DIR",
        Path(tempfile.gettempdir()) / "portfolio-fundamentals-yfinance",
    )
)

YFINANCE_CACHE.mkdir(parents=True, exist_ok=True)
try:
    yf.cache.set_cache_location(str(YFINANCE_CACHE))
except Exception as exc:  # pragma: no cover - defensive for yfinance version drift
    logging.warning("Unable to configure yfinance cache: %s", exc)

app = Flask(__name__)


@app.after_request
def add_global_markets_navigation(response):
    """Also update navigation in pre-generated portfolio HTML snapshots."""
    if response.mimetype != "text/html" or response.status_code != 200:
        return response
    response.direct_passthrough = False
    html = response.get_data(as_text=True)
    if "global_markets.html" not in html:
        html = re.sub(
            r'(<a\b[^>]*href=["\'][^"\']*bottom_fishing(?:\.html)?["\'][^>]*>.*?</a>)',
            r'\1<a href="global_markets.html">全球股市概況</a>',
            html,
            flags=re.DOTALL,
        )
        response.set_data(html)
    return response


@app.get("/global_markets.html")
@app.get("/global_markets")
def global_markets():
    """Embed the complete Market Atlas app, including its own quote API."""
    configured_url = os.environ.get("MARKET_ATLAS_URL", "").strip()
    hostname = urlsplit(request.host_url).hostname or "localhost"
    host = f"[{hostname}]" if ":" in hostname else hostname
    atlas_url = configured_url or f"http://{host}:3000/"
    if urlsplit(atlas_url).scheme not in ("http", "https"):
        return "MARKET_ATLAS_URL must be an HTTP or HTTPS URL", 500
    return render_template("global_markets.html", atlas_url=atlas_url)


FULL_PORTFOLIO = [
    {"symbol": "AAPL", "shares": 3, "cost": 288.9},
    {"symbol": "AEP", "shares": 15, "cost": 105.216},
    {"symbol": "AMZN", "shares": 18, "cost": 220.786667},
    {"symbol": "AXP", "shares": 8, "cost": 304.8725},
    {"symbol": "CDNS", "shares": 7, "cost": 329.147},
    {"symbol": "CEG", "shares": 28, "cost": 290.96},
    {"symbol": "CVX", "shares": 3, "cost": 196.3266},
    {"symbol": "DIS", "shares": 5, "cost": 98.282},
    {"symbol": "DUK", "shares": 16, "cost": 115.79375},
    {"symbol": "GOOGL", "shares": 80.47318, "cost": 185.028},
    {"symbol": "HUBB", "shares": 9, "cost": 443.946667},
    {"symbol": "HIMX", "shares": 3, "cost": 13.06},
    {"symbol": "INTC", "shares": 57, "cost": 104.4},
    {"symbol": "JNJ", "shares": 1, "cost": 249.97},
    {"symbol": "KO", "shares": 206.47431, "cost": 76.722},
    {"symbol": "LEU", "shares": 8, "cost": 165.216},
    {"symbol": "LULU", "shares": 2, "cost": 108.735},
    {"symbol": "MCD", "shares": 25, "cost": 270.79},
    {"symbol": "META", "shares": 1, "cost": 567.49},
    {"symbol": "MSFT", "shares": 1, "cost": 397.17},
    {"symbol": "MU", "shares": 12, "cost": 367.1426},
    {"symbol": "NVDA", "shares": 99.22095, "cost": 172.4558},
    {"symbol": "NFLX", "shares": 3, "cost": 73.28},
    {"symbol": "PEP", "shares": 5, "cost": 136.218},
    {"symbol": "QCOM", "shares": 1, "cost": 208.67},
    {"symbol": "SIMO", "shares": 4, "cost": 252.7225},
    {"symbol": "SNDK", "shares": 5, "cost": 1335.1},
    {"symbol": "SNPS", "shares": 13, "cost": 467.177},
    {"symbol": "TSLA", "shares": 2, "cost": 420},
    {"symbol": "TSM", "shares": 75, "cost": 415.82},
    {"symbol": "TPR", "shares": 1, "cost": 127.7},
    {"symbol": "UNH", "shares": 15, "cost": 310.86},
    {"symbol": "V", "shares": 5, "cost": 310.006},
    {"symbol": "VST", "shares": 11, "cost": 146.69},
    {"symbol": "YUM", "shares": 2, "cost": 144.73},
]

COMPANY_DESCRIPTIONS = {
    "AAPL": "Apple 設計 iPhone、Mac、iPad 與穿戴裝置，並經營 App Store、iCloud、Apple Music 等服務生態系。",
    "AEP": "American Electric Power 是美國受監管的電力公用事業，營運發電、輸電與配電網路。",
    "AMZN": "Amazon 經營電商、市集與物流服務，並透過 AWS 提供雲端運算，以及發展數位廣告業務。",
    "AXP": "American Express 同時是信用卡發卡商、支付網路與旅遊服務商，主要服務中高消費客群及企業。",
    "CDNS": "Cadence 提供電子設計自動化軟體、系統分析工具與半導體 IP，協助客戶設計晶片與電子系統。",
    "CEG": "Constellation Energy 是美國大型低碳電力供應商，以核能發電為核心，也經營天然氣與零售電力。",
    "CVX": "Chevron 是綜合能源公司，涵蓋石油天然氣探勘生產、煉油、化學品與能源銷售。",
    "DIS": "Disney 經營電影與電視內容、Disney+ 串流、ESPN 體育媒體，以及主題樂園與授權商品。",
    "DUK": "Duke Energy 是美國受監管的電力與天然氣公用事業，主要收入來自供電、配電與基礎設施投資。",
    "GOOGL": "Alphabet 以 Google 搜尋與 YouTube 廣告為核心，同時經營 Google Cloud、Android 與人工智慧產品。",
    "HUBB": "Hubbell 製造電氣與公用事業基礎設施產品，服務電網、配電、工業與建築市場。",
    "HIMX": "奇景光電是無晶圓廠 IC 設計公司，主力為顯示器驅動晶片、影像感測與相關半導體解決方案。",
    "INTC": "Intel 設計個人電腦與資料中心處理器，也投資自有晶圓製造並發展對外晶圓代工服務。",
    "JNJ": "Johnson & Johnson 聚焦創新製藥與醫療科技，產品涵蓋腫瘤、免疫、外科與介入式醫材。",
    "KO": "Coca-Cola 經營全球非酒精飲料品牌，主要透過濃縮液銷售、品牌授權與合作裝瓶網路獲利。",
    "LEU": "Centrus Energy 供應核燃料與濃縮鈾服務，並發展美國本土高濃度低濃縮鈾（HALEU）產能。",
    "LULU": "Lululemon 設計與直營運動服飾、鞋類及配件，核心品類包括瑜伽、跑步與日常機能服。",
    "MCD": "McDonald's 以全球加盟餐廳為主，收入來自加盟權利金、租金及部分自營餐廳。",
    "META": "Meta 經營 Facebook、Instagram、WhatsApp 等社群平台，以數位廣告為主，並投入 AI 與虛擬實境。",
    "MSFT": "Microsoft 提供企業軟體、Azure 雲端、Windows、Microsoft 365、遊戲與人工智慧服務。",
    "MU": "Micron 生產 DRAM、NAND 快閃記憶體與儲存產品，供應資料中心、行動裝置、汽車與消費電子。",
    "NVDA": "NVIDIA 提供 GPU、AI 加速器、網路設備與軟體平台，核心市場涵蓋資料中心、遊戲與專業視覺運算。",
    "NFLX": "Netflix 提供全球訂閱制影音串流，投資自製內容，並拓展含廣告方案與遊戲等服務。",
    "PEP": "PepsiCo 經營全球零食與飲料品牌，主要事業包括 Frito-Lay、Quaker、Pepsi 與 Gatorade。",
    "QCOM": "Qualcomm 設計行動通訊與無線連網晶片，並透過專利授權取得技術權利金。",
    "SIMO": "慧榮科技設計 NAND 快閃記憶體控制晶片，應用於 SSD、嵌入式儲存與資料中心。",
    "SNDK": "SanDisk 提供 NAND 快閃記憶體與儲存產品，服務消費電子、企業與資料中心市場。",
    "SNPS": "Synopsys 提供晶片設計自動化軟體、驗證工具與半導體 IP，是先進晶片研發的重要供應商。",
    "TSLA": "Tesla 生產電動車，並經營能源儲存、太陽能、充電網路與自動駕駛相關軟體。",
    "TSM": "台積電是專業晶圓代工公司，替全球客戶製造先進與成熟製程半導體。",
    "TPR": "Tapestry 是精品集團，旗下品牌包括 Coach、Kate Spade 與 Stuart Weitzman，主力為皮件與配飾。",
    "UNH": "UnitedHealth Group 透過 UnitedHealthcare 提供健康保險，並以 Optum 經營醫療照護、藥事與資料服務。",
    "V": "Visa 營運全球電子支付網路，連結發卡行、收單行、商戶與消費者，本身通常不承擔信用風險。",
    "VST": "Vistra 在美國競爭型電力市場經營發電與零售售電，資產組合包含核能、天然氣與儲能。",
    "YUM": "Yum! Brands 以加盟模式經營 KFC、Pizza Hut、Taco Bell 與 Habit Burger 等餐飲品牌。",
}

BUFFETT_QUOTES = [
    "投資的第一條規則是永遠不要賠錢。第二條規則是永遠不要忘記第一條，所以要買台積。",
    "價格是你所付出的，價值是你所得到的。",
    "如果找不到在睡覺時也能賺錢的方法，你將會工作一輩子到死(所以台股買台積 美股買TSM)。",
    "以合理的價格買下一家好公司，比用便宜的價格買下一家普通的公司好得多。",
    "別人恐懼我貪婪，別人貪婪我恐懼。",
    "如果你沒有持有一檔股票(台積) 10 年的想法，那連 10 分鐘都不要持有。",
    "只有當潮水退去時，才知道誰在裸泳(沒買台積)。",
    "分散投資是無知的保護傘，對於那些知道自己在做什麼的人來說，這意義不大，所以要全倉台積。",
    "不要投資於你不了解的事物。所以要投資台積",
    "ALL IN 台積就對了",
    "我們不必比別人聰明，我們只需要比別人更有紀律，死抱台積。",
    "最成功的交易是做自己喜歡的事。所以要當台積股東",
    "最好的投資就是投資自己，還有台積。",
]

SECTOR_NAMES = {
    "Technology": "科技",
    "Communication Services": "通訊服務",
    "Consumer Cyclical": "非必需消費",
    "Consumer Defensive": "必需消費",
    "Financial Services": "金融",
    "Healthcare": "醫療保健",
    "Industrials": "工業",
    "Energy": "能源",
    "Utilities": "公用事業",
    "Basic Materials": "原物料",
    "Real Estate": "房地產",
}

SEC_HEADERS = {
    "User-Agent": "FundamentalsDesk/1.0 https://fundamentals-desk-portfolio.stu1010614.chatgpt.site",
    "Accept-Encoding": "gzip, deflate",
}


def _fetch_sec_cik_map() -> dict[str, int]:
    try:
        response = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=SEC_HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        return {
            str(entry["ticker"]).upper(): int(entry["cik_str"])
            for entry in response.json().values()
        }
    except Exception as exc:
        logging.warning("SEC ticker map unavailable: %s", exc)
        return {}


def _money_from_match(value: str, unit: str) -> float:
    multiplier = 1_000_000_000 if unit.lower().startswith("b") else 1_000_000
    return float(value.replace(",", "")) * multiplier


def _fetch_buyback_program(cik: int | None) -> dict[str, Any]:
    """Extract the latest stated repurchase authorization from an SEC filing."""
    fallback = {
        "authorized_amount": None,
        "expiry": "最新財報未明確揭露",
        "form": None,
        "filed": None,
        "source_url": None,
    }
    if cik is None:
        return fallback
    try:
        cik_text = f"{cik:010d}"
        submissions = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik_text}.json",
            headers=SEC_HEADERS,
            timeout=20,
        )
        submissions.raise_for_status()
        recent = submissions.json()["filings"]["recent"]
        filing = next(
            (
                {"accession": accession, "document": document, "filed": filed, "form": form}
                for accession, document, filed, form in zip(
                    recent["accessionNumber"],
                    recent["primaryDocument"],
                    recent["filingDate"],
                    recent["form"],
                )
                if form in {"10-Q", "10-K", "20-F", "40-F"}
            ),
            None,
        )
        if not filing:
            return fallback
        accession_plain = filing["accession"].replace("-", "")
        source_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_plain}/"
            f"{filing['document']}"
        )
        document = requests.get(source_url, headers=SEC_HEADERS, timeout=25)
        document.raise_for_status()
        text = " ".join(BeautifulSoup(document.text, "html.parser").get_text(" ").split())

        money = r"\$\s*([0-9][0-9,.]*(?:\.[0-9]+)?)\s*(billion|million)"
        patterns = [
            rf"(?:announced|authorized|approved)[^.]{{0,240}}?(?:program|plan|authorization)[^.]{{0,160}}?(?:repurchase|purchase|buy back)[^.]{{0,120}}?{money}",
            rf"(?:program|plan|authorization)[^.]{{0,180}}?(?:repurchase|buy back)[^.]{{0,140}}?(?:up to|aggregate amount of|totaling)[^.]{{0,30}}?{money}",
            rf"(?:authorized|approved)[^.]{{0,180}}?{money}[^.]{{0,140}}?(?:repurchase|buyback|buy back)",
        ]
        matches = [
            match
            for pattern in patterns
            for match in re.finditer(pattern, text, flags=re.IGNORECASE)
        ]
        authorized_amount = None
        expiry = fallback["expiry"]
        if matches:
            latest_match = max(matches, key=lambda match: match.start())
            authorized_amount = _money_from_match(
                latest_match.group(1), latest_match.group(2)
            )
            context = text[
                max(0, latest_match.start() - 450) : latest_match.end() + 1100
            ]
            if re.search(
                r"(?:does not have|has no|without|no) (?:a )?(?:fixed )?expiration date",
                context,
                flags=re.IGNORECASE,
            ):
                expiry = "無固定期限"
            else:
                date_match = re.search(
                    r"(?:expires?|expiration date (?:is|of))\s+(?:on\s+)?"
                    r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4}|[A-Z][a-z]+\s+\d{4}|\d{4})",
                    context,
                    flags=re.IGNORECASE,
                )
                if date_match:
                    expiry = date_match.group(1)

        return {
            "authorized_amount": authorized_amount,
            "expiry": expiry,
            "form": filing["form"],
            "filed": filing["filed"],
            "source_url": source_url,
        }
    except Exception as exc:
        logging.warning("SEC buyback program unavailable for CIK %s: %s", cik, exc)
        return fallback


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _positive_metric(value: Any) -> float | None:
    result = _safe_float(value)
    return result if result is not None and result > 0 else None


def _latest_price(info: dict[str, Any], history: pd.DataFrame) -> float | None:
    for field in ("currentPrice", "regularMarketPrice", "previousClose"):
        price = _positive_metric(info.get(field))
        if price is not None:
            return price
    if not history.empty and "Close" in history:
        return _positive_metric(history["Close"].dropna().iloc[-1])
    return None


def _all_time_high(history: pd.DataFrame) -> float | None:
    if history.empty or "High" not in history:
        return None
    values = pd.to_numeric(history["High"], errors="coerce").dropna()
    return _positive_metric(values.max()) if not values.empty else None


def _buyback_activity(cashflow: pd.DataFrame) -> dict[str, Any]:
    """Return repurchase cash outflow and the latest disclosure period."""
    if cashflow.empty:
        return {"amount": None, "period_end": None}
    period_dates = pd.to_datetime(cashflow.columns, errors="coerce")
    valid_period_dates = period_dates[~pd.isna(period_dates)]
    period_end = (
        max(valid_period_dates).strftime("%Y-%m-%d")
        if len(valid_period_dates)
        else None
    )
    candidates = [
        index
        for index in cashflow.index
        if "repurchase" in str(index).lower()
        and ("stock" in str(index).lower() or "capital" in str(index).lower())
    ]
    if not candidates:
        return {"amount": 0.0, "period_end": period_end}
    values = pd.to_numeric(cashflow.loc[candidates[0]], errors="coerce").dropna().iloc[:4]
    if values.empty:
        return {"amount": None, "period_end": period_end}
    # Yahoo reports repurchases as a negative cash-flow item. Positive values are
    # excluded because they normally represent reversals rather than cash spent.
    spent = float((-values[values < 0]).sum())
    return {"amount": spent if spent > 0 else 0.0, "period_end": period_end}


def _buyback_ttm(cashflow: pd.DataFrame) -> float | None:
    """Return gross repurchases reported in the latest four available quarters."""
    return _buyback_activity(cashflow)["amount"]


def _fundamental_label(roa: float | None, forward_pe: float | None) -> str:
    if roa is not None and roa < 0:
        return "ROA 為負"
    if roa is None or forward_pe is None:
        return "指標待補"
    return "需搭配產業與成長假設"


def _empty_snapshot(position: dict[str, Any], error: str | None = None) -> dict[str, Any]:
    shares = float(position["shares"])
    cost = float(position["cost"])
    return {
        "symbol": position["symbol"],
        "name": position["symbol"],
        "sector": "其他",
        "industry": None,
        "business_description": COMPANY_DESCRIPTIONS.get(position["symbol"], ""),
        "shares": shares,
        "cost": cost,
        "cost_basis": shares * cost,
        "price": None,
        "market_value": None,
        "portfolio_weight": None,
        "roi": None,
        "trailing_pe": None,
        "forward_pe": None,
        "roa": None,
        "roe": None,
        "ath": None,
        "ath_distance": None,
        "buyback_ttm": None,
        "buyback_period_end": None,
        "buyback_authorized_amount": None,
        "buyback_program_expiry": None,
        "buyback_program_form": None,
        "buyback_program_filed": None,
        "buyback_program_source_url": None,
        "is_buying_back": None,
        "currency": "USD",
        "label": "資料待補",
        "quote_url": f"https://finance.yahoo.com/quote/{position['symbol']}",
        "data_status": "unavailable",
        "error": error,
    }


def fetch_stock_snapshot(
    position: dict[str, Any], sec_cik: int | None = None
) -> dict[str, Any]:
    """Fetch one holding while preserving partial data when a source is unavailable."""
    item = _empty_snapshot(position)
    ticker = yf.Ticker(position["symbol"])

    try:
        info = ticker.get_info() or {}
    except Exception as exc:
        logging.warning("%s info unavailable: %s", position["symbol"], exc)
        info = {}

    try:
        history = ticker.history(
            period="max", interval="1d", auto_adjust=True, actions=False, timeout=20
        )
    except Exception as exc:
        logging.warning("%s history unavailable: %s", position["symbol"], exc)
        history = pd.DataFrame()

    try:
        cashflow = ticker.get_cash_flow(freq="quarterly")
        buyback_activity = _buyback_activity(cashflow)
        buyback = buyback_activity["amount"]
        buyback_period_end = buyback_activity["period_end"]
    except Exception as exc:
        logging.warning("%s cash flow unavailable: %s", position["symbol"], exc)
        buyback = None
        buyback_period_end = None

    buyback_program = (
        _fetch_buyback_program(sec_cik)
        if sec_cik is not None
        else {
            "authorized_amount": None,
            "expiry": "—",
            "form": None,
            "filed": None,
            "source_url": None,
        }
    )

    price = _latest_price(info, history)
    ath = _all_time_high(history)
    shares = float(position["shares"])
    cost = float(position["cost"])
    market_value = price * shares if price is not None else None
    roi = ((price / cost) - 1) * 100 if price is not None and cost else None
    ath_distance = ((price / ath) - 1) * 100 if price is not None and ath else None
    trailing_pe = _positive_metric(info.get("trailingPE"))
    forward_pe = _positive_metric(info.get("forwardPE"))
    roa_raw = _safe_float(info.get("returnOnAssets"))
    roa = roa_raw * 100 if roa_raw is not None else None
    roe_raw = _safe_float(info.get("returnOnEquity"))
    roe = roe_raw * 100 if roe_raw is not None else None

    item.update(
        {
            "name": info.get("shortName") or info.get("longName") or position["symbol"],
            "sector": SECTOR_NAMES.get(info.get("sector"), info.get("sector") or "其他"),
            "industry": info.get("industry"),
            "business_description": COMPANY_DESCRIPTIONS.get(position["symbol"])
            or info.get("longBusinessSummary")
            or "尚無公司業務描述。",
            "price": price,
            "market_value": market_value,
            "roi": roi,
            "trailing_pe": trailing_pe,
            "forward_pe": forward_pe,
            "roa": roa,
            "roe": roe,
            "forward_eps": _safe_float(info.get("forwardEps")),
            "trailing_eps": _safe_float(info.get("trailingEps")),
            "book_value": _safe_float(info.get("bookValue")),
            "financial_currency": info.get("financialCurrency"),
            "fcf_currency": info.get("financialCurrency"),
            "revenue_growth": _safe_float(info.get("revenueGrowth")),
            "profit_margin": _safe_float(info.get("profitMargins")),
            "free_cashflow": _safe_float(info.get("freeCashflow")),
            "company_market_cap": _positive_metric(info.get("marketCap")),
            "ath": ath,
            "ath_distance": min(ath_distance, 0.0) if ath_distance is not None else None,
            "buyback_ttm": buyback,
            "buyback_period_end": buyback_period_end,
            "buyback_authorized_amount": buyback_program["authorized_amount"],
            "buyback_program_expiry": buyback_program["expiry"],
            "buyback_program_form": buyback_program["form"],
            "buyback_program_filed": buyback_program["filed"],
            "buyback_program_source_url": buyback_program["source_url"],
            "is_buying_back": buyback > 0 if buyback is not None else None,
            "currency": info.get("currency") or "USD",
            "label": _fundamental_label(roa, forward_pe),
            "data_status": "live" if price is not None else "partial",
            "error": None,
        }
    )
    item["fundamental_period"] = (
        datetime.fromtimestamp(info["mostRecentQuarter"], timezone("UTC")).strftime("%Y-%m-%d")
        if info.get("mostRecentQuarter") else "來源未提供財報期末"
    )
    item["fetched_at"] = datetime.now(timezone("Asia/Taipei")).isoformat()
    if item["free_cashflow"] is None or item.get("fcf_currency") != item["currency"]:
        fallback = fetch_cashflow_fallback(position["symbol"])
        if fallback:
            item.update(fallback)
    return apply_reviewed_data(item)


def _load_cache() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(SNAPSHOT_CACHE.read_text(encoding="utf-8"))
        return {item["symbol"]: item for item in data.get("items", [])}
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        return {}


def _write_cache(items: list[dict[str, Any]]) -> None:
    SNAPSHOT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone("Asia/Taipei")).isoformat(),
        "items": items,
    }
    SNAPSHOT_CACHE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _merge_with_cache(
    fetched: dict[str, Any], cached: dict[str, Any] | None
) -> dict[str, Any]:
    if not cached:
        return fetched
    if fetched.get("data_status") == "live":
        return fetched
    preserved = dict(cached)
    preserved.update(
        {
            "shares": fetched["shares"],
            "cost": fetched["cost"],
            "cost_basis": fetched["cost_basis"],
            "roi": (
                ((preserved.get("price") / fetched["cost"]) - 1) * 100
                if preserved.get("price") is not None and fetched["cost"]
                else None
            ),
            "data_status": "cached",
        }
    )
    return preserved


def _weighted_average(
    items: list[dict[str, Any]], field: str, weight_field: str = "market_value"
) -> float | None:
    valid = [
        item
        for item in items
        if item.get(field) is not None and item.get(weight_field) is not None
    ]
    denominator = sum(float(item[weight_field]) for item in valid)
    if not denominator:
        return None
    return sum(float(item[field]) * float(item[weight_field]) for item in valid) / denominator


def build_dashboard_data(max_workers: int = 4) -> dict[str, Any]:
    cached = _load_cache()
    sec_cik_map = _fetch_sec_cik_map()
    fetched_by_symbol: dict[str, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                fetch_stock_snapshot, position, sec_cik_map.get(position["symbol"])
            ): position
            for position in FULL_PORTFOLIO
        }
        for future in as_completed(futures):
            position = futures[future]
            try:
                fetched = future.result()
            except Exception as exc:  # pragma: no cover - final safety net
                logging.exception("Failed to fetch %s", position["symbol"])
                fetched = _empty_snapshot(position, str(exc))
            fetched_by_symbol[position["symbol"]] = _merge_with_cache(
                fetched, cached.get(position["symbol"])
            )

    items = [fetched_by_symbol[position["symbol"]] for position in FULL_PORTFOLIO]
    total_market_value = sum(item.get("market_value") or 0 for item in items)
    total_cost = sum(item["cost_basis"] for item in items)
    for item in items:
        item["portfolio_weight"] = (
            item["market_value"] / total_market_value * 100
            if item.get("market_value") is not None and total_market_value
            else None
        )

    live_or_partial = [item for item in items if item["data_status"] != "unavailable"]
    if live_or_partial:
        _write_cache(live_or_partial)

    total_roi = (
        (total_market_value / total_cost - 1) * 100
        if total_market_value and total_cost
        else None
    )
    unrealized_profit = (
        total_market_value - total_cost if total_market_value is not None else None
    )
    top_10_value = sum(
        sorted(
            (item.get("market_value") or 0 for item in items), reverse=True
        )[:10]
    )
    top_10_concentration = (
        top_10_value / total_market_value * 100 if total_market_value else None
    )
    sectors: dict[str, float] = {}
    for item in items:
        sectors[item["sector"]] = sectors.get(item["sector"], 0) + (
            item.get("market_value") or 0
        )

    sector_mix = [
        {
            "name": name,
            "value": value,
            "weight": value / total_market_value * 100 if total_market_value else 0,
        }
        for name, value in sorted(sectors.items(), key=lambda pair: pair[1], reverse=True)
    ]

    now_taipei = datetime.now(timezone("Asia/Taipei"))
    day_of_year = now_taipei.timetuple().tm_yday
    today_quote = BUFFETT_QUOTES[day_of_year % len(BUFFETT_QUOTES)]

    return {
        "generated_at": now_taipei.strftime("%Y.%m.%d %H:%M TPE"),
        "today_quote": today_quote,
        "items": items,
        "sector_mix": sector_mix,
        "summary": {
            "holdings_count": len(items),
            "total_market_value": total_market_value or None,
            "total_cost": total_cost,
            "total_roi": total_roi,
            "unrealized_profit": unrealized_profit,
            "top_10_concentration": top_10_concentration,
            "coverage_count": sum(
                item.get("trailing_pe") is not None
                or item.get("forward_pe") is not None
                or item.get("roa") is not None
                or item.get("roe") is not None
                for item in items
            ),
        },
    }


def prepare_research_data(data: dict[str, Any]) -> dict[str, Any]:
    """Enrich live and legacy snapshots without inventing unavailable history."""
    items = []
    for original in data.get("items", []):
        item = apply_reviewed_data(original)
        for field in ("price", "trailing_pe", "forward_pe", "roa", "roe",
                      "forward_eps", "revenue_growth", "profit_margin",
                      "free_cashflow", "company_market_cap"):
            item[field] = _safe_float(item.get(field))
        price, forward = item["price"], _positive_metric(item["forward_pe"])
        eps = item["forward_eps"]
        item["eps_source"] = "Yahoo Finance forwardEps（預估期間依來源定義）"
        if eps is None and price and forward:
            eps = price / forward
            item["eps_source"] = "現價 ÷ Forward P/E 推算；非獨立 EPS 預測"
        item["scenario_eps"] = eps if eps is not None and eps > 0 else None
        trailing = _positive_metric(item["trailing_pe"])
        item["implied_eps_change"] = (trailing / forward - 1) * 100 if trailing and forward else None
        cap = _positive_metric(item.get("fcf_market_cap") or item["company_market_cap"])
        currency_matches = item.get("fcf_currency", item.get("currency")) == item.get("currency")
        item["fcf_yield"] = item["free_cashflow"] / cap * 100 if item["free_cashflow"] is not None and cap and currency_matches else None
        notes = []
        if item.get("data_status") == "cached":
            notes.append("使用快取資料，請先核對資料日期")
        if item.get("reviewed_data_stale"):
            notes.append("回購人工核對資料需更新；下方僅列歷史披露，不代表現行額度")
        for status in item.get("metric_status", {}).values():
            if status not in notes:
                notes.append(status)
        if item["scenario_eps"] is None:
            notes.append("缺少正值預估 EPS；請自行輸入假設或改用其他估值方法")
        if item["roa"] is not None and item["roa"] < 0:
            notes.append("ROA 為負，需檢查虧損原因與盈餘恢復假設")
        change = item["implied_eps_change"]
        if change is not None and abs(change) >= 30:
            notes.append("兩種 P/E 隱含 EPS 差異達 30%：核對期間、一次性損益與預估假設")
        missing = [label for key, label in (("roa", "ROA"), ("roe", "ROE"), ("fcf_yield", "FCF 殖利率")) if item[key] is None and key not in item.get("metric_status", {})]
        if missing:
            notes.append("待補資料：" + "、".join(missing))
        item["research_notes"] = notes
        item["label"] = _fundamental_label(item["roa"], forward)
        items.append(item)
    return {**data, "items": items}


def render_dashboard(
    data: dict[str, Any] | None = None,
    asset_prefix: str = "/static",
    og_image_url: str | None = None,
) -> str:
    return render_template(
        "fundamentals.html",
        dashboard=prepare_research_data(data if data is not None else build_dashboard_data()),
        asset_prefix=asset_prefix,
        og_image_url=og_image_url
        or f"{os.environ.get('SITE_URL', 'https://huangchink.github.io/portfolio').rstrip('/')}/{asset_prefix.lstrip('/')}/og.png",
    )


@app.get("/")
@app.get("/fundamentals.html")
def index():
    snapshot = PROJECT_ROOT / "docs" / "fundamentals.html"
    if snapshot.is_file():
        return send_file(snapshot, mimetype="text/html")
    return render_dashboard()


@app.get("/index.html")
def portfolio_overview():
    """Serve the overview linked from the fundamentals navigation."""
    snapshot = PROJECT_ROOT / "docs" / "index.html"
    if snapshot.is_file():
        return send_file(snapshot, mimetype="text/html")
    # A fresh checkout may not have a generated snapshot yet.
    from portfolio import render_portfolio_html

    return render_portfolio_html()


@app.get("/bottom_fishing.html")
@app.get("/bottom_fishing")
def bottom_fishing():
    """Serve the bottom-fishing strategy linked from navigation."""
    snapshot = PROJECT_ROOT / "docs" / "bottom_fishing.html"
    if snapshot.is_file():
        return send_file(snapshot, mimetype="text/html")
    from portfolio import render_bottom_fishing_html

    return render_bottom_fishing_html()


@app.get("/assets/<path:filename>")
def serve_assets(filename: str):
    """Serve static assets referenced by docs HTML snapshots."""
    asset_dir = PROJECT_ROOT / "docs" / "assets"
    if (asset_dir / filename).is_file():
        return send_from_directory(asset_dir, filename)
    return send_from_directory(PROJECT_ROOT / "static", filename)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def write_static_site(output_path: Path, data: dict[str, Any] | None = None) -> None:
    data = data or build_dashboard_data()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        output_path.write_text(
            render_dashboard(data=data, asset_prefix="assets"), encoding="utf-8"
        )
    asset_dir = output_path.parent / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    for name in ("dashboard.css", "dashboard.js", "research.css", "research.js", "og.png"):
        shutil.copy2(PROJECT_ROOT / "static" / name, asset_dir / name)
    with app.app_context():
        output_path.parent.joinpath("global_markets.html").write_text(
            render_template(
                "global_markets.html",
                atlas_url=os.environ.get(
                    "MARKET_ATLAS_URL",
                    "https://market-atlas-tw.stu1010614.chatgpt.site/",
                ),
            ),
            encoding="utf-8",
        )
    print(f"Wrote fundamentals dashboard to {output_path}")


def write_sites_dist(max_workers: int = 4) -> None:
    # Keep the shared navigation consistent: index is the portfolio overview.
    for name in ("index.html", "bottom_fishing.html"):
        if not (PROJECT_ROOT / "docs" / name).is_file():
            raise FileNotFoundError(f"Generate docs/{name} before building the Sites bundle")
    data = build_dashboard_data(max_workers=max_workers)
    client_dir = PROJECT_ROOT / "dist" / "client"
    write_static_site(client_dir / "fundamentals.html", data=data)
    with app.app_context():
        (client_dir / "global_markets.html").write_text(
            render_template(
                "global_markets.html",
                atlas_url=os.environ.get(
                    "MARKET_ATLAS_URL",
                    "https://market-atlas-tw.stu1010614.chatgpt.site/",
                ),
            ),
            encoding="utf-8",
        )
    for name in ("index.html", "bottom_fishing.html"):
        shutil.copy2(PROJECT_ROOT / "docs" / name, client_dir / name)
    server_dir = PROJECT_ROOT / "dist" / "server"
    server_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROJECT_ROOT / "worker" / "index.js", server_dir / "index.js")
    print(f"Wrote Sites worker to {server_dir / 'index.js'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Portfolio fundamentals dashboard")
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("--output", type=Path, help="Generate a static site snapshot")
    output_group.add_argument(
        "--sites-dist", action="store_true", help="Generate the private Sites bundle"
    )
    parser.add_argument("--serve", action="store_true", help="Run the Flask server")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5000)))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    if args.output:
        data = build_dashboard_data(max_workers=max(1, args.workers))
        write_static_site(args.output, data=data)
        if not args.serve:
            return

    if args.sites_dist:
        write_sites_dist(max_workers=max(1, args.workers))
        if not args.serve:
            return

    if args.serve or (not args.output and not args.sites_dist):
        app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
