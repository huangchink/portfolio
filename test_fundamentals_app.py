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
                pd.Timestamp("2026-06-30"): [-120.0],
                pd.Timestamp("2026-03-31"): [-100.0],
                pd.Timestamp("2025-12-31"): [-90.0],
                pd.Timestamp("2025-09-30"): [-80.0],
                pd.Timestamp("2025-06-30"): [-70.0],
            },
            index=["Repurchase Of Capital Stock"],
        )
        self.assertEqual(dashboard._buyback_ttm(cashflow), 390.0)

    def test_buyback_ttm_returns_zero_when_cashflow_has_no_repurchases(self):
        cashflow = pd.DataFrame(
            {"2026-Q2": [-10.0]}, index=["Capital Expenditure"]
        )
        self.assertEqual(dashboard._buyback_ttm(cashflow), 0.0)

    def test_buyback_activity_includes_latest_disclosure_period(self):
        cashflow = pd.DataFrame(
            {pd.Timestamp("2026-06-30"): [-120.0]},
            index=["Repurchase Of Capital Stock"],
        )
        self.assertEqual(
            dashboard._buyback_activity(cashflow),
            {"amount": 120.0, "period_end": "2026-06-30"},
        )

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
                "roa": 18.0,
                "ath": 150.0,
                "ath_distance": -20.0,
                "buyback_ttm": 1_000_000.0,
                "buyback_period_end": "2026-06-30",
                "buyback_authorized_amount": 5_000_000_000.0,
                "buyback_program_expiry": "無固定期限",
                "buyback_program_form": "10-Q",
                "buyback_program_filed": "2026-07-31",
                "buyback_program_source_url": "https://www.sec.gov/example",
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
                "unrealized_profit": 40.0,
                "top_10_concentration": 100.0,
                "median_forward_pe": 20.0,
                "weighted_roa": 18.0,
                "buyback_count": 1,
                "near_ath_count": 0,
                "coverage_count": 1,
            },
        }
        with dashboard.app.app_context():
            html = dashboard.render_dashboard(data, asset_prefix="assets")
        for text in (
            "Forward P/E",
            "ROA",
            "持倉總 ROI",
            "股票回購",
            "距ATH",
            "前十大持股",
            "holdingsDonutCanvas",
            "最新授權規模",
            "近四季實際執行",
            "計畫期限",
        ):
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
                "unrealized_profit": None,
                "top_10_concentration": None,
                "median_forward_pe": None,
                "weighted_roa": None,
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
