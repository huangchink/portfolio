import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import fundamentals_app as dashboard


class FundamentalCalculationsTest(unittest.TestCase):
    def test_buyback_ttm_sums_latest_four_cash_outflows(self):
        cashflow = pd.DataFrame(
            {
                "2026-Q2": [-120.0],
                "2026-Q1": [-100.0],
                "2025-Q4": [-90.0],
                "2025-Q3": [-80.0],
                "2025-Q2": [-70.0],
            },
            index=["Repurchase Of Capital Stock"],
        )
        self.assertEqual(dashboard._buyback_ttm(cashflow), 390.0)

    def test_buyback_ttm_returns_zero_when_cashflow_has_no_repurchases(self):
        cashflow = pd.DataFrame(
            {"2026-Q2": [-10.0]}, index=["Capital Expenditure"]
        )
        self.assertEqual(dashboard._buyback_ttm(cashflow), 0.0)

    def test_rendered_dashboard_contains_requested_metrics(self):
        item = dashboard._empty_snapshot(
            {"symbol": "TEST", "shares": 2, "cost": 100}
        )
        item.update(
            {
                "name": "Test Company",
                "sector": "科技",
                "price": 120.0,
                "market_value": 240.0,
                "portfolio_weight": 100.0,
                "roi": 20.0,
                "trailing_pe": 24.0,
                "forward_pe": 20.0,
                "roe": 18.0,
                "ath": 150.0,
                "ath_distance": -20.0,
                "buyback_ttm": 1_000_000.0,
                "is_buying_back": True,
                "label": "品質與估值兼具",
            }
        )
        data = {
            "generated_at": "2026.09.05 12:00 TPE",
            "items": [item],
            "sector_mix": [{"name": "科技", "value": 240.0, "weight": 100.0}],
            "summary": {
                "holdings_count": 1,
                "total_market_value": 240.0,
                "total_cost": 200.0,
                "total_roi": 20.0,
                "median_forward_pe": 20.0,
                "weighted_roe": 18.0,
                "buyback_count": 1,
                "near_ath_count": 0,
                "coverage_count": 1,
            },
        }
        with dashboard.app.app_context():
            html = dashboard.render_dashboard(data, asset_prefix="assets")
        for text in ("Forward P/E", "ROE", "持倉 ROI", "股票回購", "距 ATH"):
            self.assertIn(text, html)
        self.assertIn("TEST", html)

    def test_static_writer_copies_assets(self):
        fixture = {
            "generated_at": "2026.09.05 12:00 TPE",
            "items": [],
            "sector_mix": [],
            "summary": {
                "holdings_count": 0,
                "total_market_value": None,
                "total_cost": 0,
                "total_roi": None,
                "median_forward_pe": None,
                "weighted_roe": None,
                "buyback_count": 0,
                "near_ath_count": 0,
                "coverage_count": 0,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "index.html"
            with patch.object(dashboard, "build_dashboard_data", return_value=fixture):
                dashboard.write_static_site(target)
            self.assertTrue(target.exists())
            self.assertTrue((target.parent / "assets" / "dashboard.css").exists())
            self.assertTrue((target.parent / "assets" / "dashboard.js").exists())
            self.assertTrue((target.parent / "assets" / "og.png").exists())


if __name__ == "__main__":
    unittest.main()
