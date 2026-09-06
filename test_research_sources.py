import unittest
from unittest.mock import patch
from research_data_sources import parse_scaled_number, parse_stockanalysis_cashflow, apply_reviewed_data
from fundamentals_app import prepare_research_data


class ResearchSourcesTest(unittest.TestCase):
    def test_units_missing_negative_and_rounded_cashflows(self):
        self.assertEqual(parse_scaled_number('15.05B'), 15050000000)
        self.assertEqual(parse_scaled_number('-3.43B'), -3430000000)
        self.assertEqual(parse_scaled_number('1.98T'), 1980000000000)
        for text in ('n/a', '--', '1.2B USD', ''):
            self.assertIsNone(parse_scaled_number(text))

    def test_fallback_requires_cashflow_and_same_usd_market_cap(self):
        html='<p>NYSE: AXP · Real-Time Price · USD</p><table><tr><td>Market Cap</td><td>220.26B</td></tr><tr><td>Free Cash Flow</td><td>15.05B</td></tr></table><p>Last updated: Sep 6, 2026</p>'
        result=parse_stockanalysis_cashflow(html)
        self.assertEqual(result['free_cashflow'],15050000000)
        self.assertEqual(result['fcf_market_cap'],220260000000)
        self.assertIsNone(parse_stockanalysis_cashflow(html.replace('USD','TWD')))
        self.assertIsNone(parse_stockanalysis_cashflow(html.replace('15.05B','n/a')))

    def test_currency_mismatch_never_becomes_a_yield(self):
        item={'symbol':'TEST','price':100,'currency':'USD','fcf_currency':'TWD','free_cashflow':3000,'company_market_cap':10000}
        self.assertIsNone(prepare_research_data({'items':[item]})['items'][0]['fcf_yield'])
        item.update(fcf_currency='USD',fcf_market_cap=20000)
        self.assertEqual(prepare_research_data({'items':[item]})['items'][0]['fcf_yield'],15)

    def test_negative_equity_and_earnings_have_reasons_not_invented_values(self):
        result=apply_reviewed_data({'symbol':'TEST','roe':None,'book_value':-3,'trailing_pe':None,'trailing_eps':-1},records={})
        self.assertIn('roe',result['metric_status'])
        self.assertIn('trailing_pe',result['metric_status'])
        self.assertIsNone(result['roe'])
        recovered=apply_reviewed_data({'symbol':'TEST','roe':12,'book_value':5,'trailing_pe':20,'trailing_eps':2},records={})
        self.assertEqual(recovered['metric_status'],{})

    def test_review_preserves_share_units_and_historical_period(self):
        records={'TEST':{'reviewed_at':'2026-09-06','source':{'filed':'2026-08-01'},'buyback':{'authorization':'120 million shares','expiry':'not disclosed'}}}
        result=apply_reviewed_data({'symbol':'TEST','buyback_program_filed':'2026-09-01'},records)
        self.assertEqual(result['reviewed_buyback']['authorization'],'120 million shares')
        self.assertTrue(result['reviewed_data_stale'])
        self.assertNotIn('buyback_authorized_amount',result)


if __name__=='__main__':unittest.main()
