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
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf
from flask import Flask, render_template
from pytz import timezone


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


def _buyback_ttm(cashflow: pd.DataFrame) -> float | None:
    """Return gross repurchases reported in the latest four available quarters."""
    if cashflow.empty:
        return None
    candidates = [
        index
        for index in cashflow.index
        if "repurchase" in str(index).lower()
        and ("stock" in str(index).lower() or "capital" in str(index).lower())
    ]
    if not candidates:
        return 0.0
    values = pd.to_numeric(cashflow.loc[candidates[0]], errors="coerce").dropna().iloc[:4]
    if values.empty:
        return None
    # Yahoo reports repurchases as a negative cash-flow item. Positive values are
    # excluded because they normally represent reversals rather than cash spent.
    spent = float((-values[values < 0]).sum())
    return spent if spent > 0 else 0.0


def _fundamental_label(roe: float | None, forward_pe: float | None) -> str:
    if roe is None and forward_pe is None:
        return "資料待補"
    if roe is not None and roe >= 20 and forward_pe is not None and forward_pe <= 30:
        return "品質與估值兼具"
    if roe is not None and roe >= 20:
        return "高 ROE・估值偏高"
    if forward_pe is not None and forward_pe <= 20:
        return "估值具吸引力"
    if roe is not None and roe < 0:
        return "獲利品質待改善"
    return "中性觀察"


def _empty_snapshot(position: dict[str, Any], error: str | None = None) -> dict[str, Any]:
    shares = float(position["shares"])
    cost = float(position["cost"])
    return {
        "symbol": position["symbol"],
        "name": position["symbol"],
        "sector": "其他",
        "shares": shares,
        "cost": cost,
        "cost_basis": shares * cost,
        "price": None,
        "market_value": None,
        "portfolio_weight": None,
        "roi": None,
        "trailing_pe": None,
        "forward_pe": None,
        "roe": None,
        "ath": None,
        "ath_distance": None,
        "buyback_ttm": None,
        "is_buying_back": None,
        "currency": "USD",
        "label": "資料待補",
        "quote_url": f"https://finance.yahoo.com/quote/{position['symbol']}",
        "data_status": "unavailable",
        "error": error,
    }


def fetch_stock_snapshot(position: dict[str, Any]) -> dict[str, Any]:
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
        buyback = _buyback_ttm(cashflow)
    except Exception as exc:
        logging.warning("%s cash flow unavailable: %s", position["symbol"], exc)
        buyback = None

    price = _latest_price(info, history)
    ath = _all_time_high(history)
    shares = float(position["shares"])
    cost = float(position["cost"])
    market_value = price * shares if price is not None else None
    roi = ((price / cost) - 1) * 100 if price is not None and cost else None
    ath_distance = ((price / ath) - 1) * 100 if price is not None and ath else None
    trailing_pe = _positive_metric(info.get("trailingPE"))
    forward_pe = _positive_metric(info.get("forwardPE"))
    roe_raw = _safe_float(info.get("returnOnEquity"))
    roe = roe_raw * 100 if roe_raw is not None else None

    item.update(
        {
            "name": info.get("shortName") or info.get("longName") or position["symbol"],
            "sector": SECTOR_NAMES.get(info.get("sector"), info.get("sector") or "其他"),
            "price": price,
            "market_value": market_value,
            "roi": roi,
            "trailing_pe": trailing_pe,
            "forward_pe": forward_pe,
            "roe": roe,
            "ath": ath,
            "ath_distance": min(ath_distance, 0.0) if ath_distance is not None else None,
            "buyback_ttm": buyback,
            "is_buying_back": buyback > 0 if buyback is not None else None,
            "currency": info.get("currency") or "USD",
            "label": _fundamental_label(roe, forward_pe),
            "data_status": "live" if price is not None else "partial",
            "error": None,
        }
    )
    return item


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
    fetched_by_symbol: dict[str, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(fetch_stock_snapshot, position): position
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
    forward_values = sorted(
        item["forward_pe"] for item in items if item.get("forward_pe") is not None
    )
    median_forward_pe = (
        float(pd.Series(forward_values).median()) if forward_values else None
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

    return {
        "generated_at": datetime.now(timezone("Asia/Taipei")).strftime(
            "%Y.%m.%d %H:%M TPE"
        ),
        "items": items,
        "sector_mix": sector_mix,
        "summary": {
            "holdings_count": len(items),
            "total_market_value": total_market_value or None,
            "total_cost": total_cost,
            "total_roi": total_roi,
            "median_forward_pe": median_forward_pe,
            "weighted_roe": _weighted_average(items, "roe"),
            "buyback_count": sum(item.get("is_buying_back") is True for item in items),
            "near_ath_count": sum(
                item.get("ath_distance") is not None and item["ath_distance"] >= -10
                for item in items
            ),
            "coverage_count": sum(
                item.get("trailing_pe") is not None
                or item.get("forward_pe") is not None
                or item.get("roe") is not None
                for item in items
            ),
        },
    }


def render_dashboard(
    data: dict[str, Any] | None = None,
    asset_prefix: str = "/static",
    og_image_url: str | None = None,
) -> str:
    return render_template(
        "fundamentals.html",
        dashboard=data or build_dashboard_data(),
        asset_prefix=asset_prefix,
        og_image_url=og_image_url
        or f"{os.environ.get('SITE_URL', 'https://huangchink.github.io/portfolio').rstrip('/')}/{asset_prefix.lstrip('/')}/og.png",
    )


@app.get("/")
def index() -> str:
    return render_dashboard()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def write_static_site(output_path: Path) -> None:
    data = build_dashboard_data()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        output_path.write_text(
            render_dashboard(data=data, asset_prefix="assets"), encoding="utf-8"
        )
    asset_dir = output_path.parent / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    for name in ("dashboard.css", "dashboard.js", "og.png"):
        shutil.copy2(PROJECT_ROOT / "static" / name, asset_dir / name)
    print(f"Wrote fundamentals dashboard to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Portfolio fundamentals dashboard")
    parser.add_argument("--output", type=Path, help="Generate a static site snapshot")
    parser.add_argument("--serve", action="store_true", help="Run the Flask server")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5000)))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    if args.output:
        # Keep worker count configurable for CI environments with stricter rate limits.
        original_builder = build_dashboard_data
        if args.workers != 4:
            data = original_builder(max_workers=max(1, args.workers))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with app.app_context():
                args.output.write_text(
                    render_dashboard(data=data, asset_prefix="assets"), encoding="utf-8"
                )
            asset_dir = args.output.parent / "assets"
            asset_dir.mkdir(parents=True, exist_ok=True)
            for name in ("dashboard.css", "dashboard.js", "og.png"):
                shutil.copy2(PROJECT_ROOT / "static" / name, asset_dir / name)
            print(f"Wrote fundamentals dashboard to {args.output}")
        else:
            write_static_site(args.output)
        if not args.serve:
            return

    if args.serve or not args.output:
        app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
