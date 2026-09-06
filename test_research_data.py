import unittest
from fundamentals_app import prepare_research_data, _empty_snapshot


class ResearchDataTest(unittest.TestCase):
    def item(self, **overrides):
        item = _empty_snapshot({'symbol': 'TEST', 'shares': 2, 'cost': 100})
        item.update(overrides)
        return item

    def enrich(self, item):
        return prepare_research_data({'items': [item]})['items'][0]

    def test_legacy_snapshot_uses_disclosed_implied_eps(self):
        source = self.item(price=120, forward_pe=20, trailing_pe=30)
        item = self.enrich(source)
        self.assertEqual(item['scenario_eps'], 6)
        self.assertEqual(item['implied_eps_change'], 50)
        self.assertIn('推算', item['eps_source'])
        self.assertIsNone(item['fcf_yield'])
        self.assertNotIn('scenario_eps', source)

    def test_direct_eps_overrides_derived_value_and_negative_is_not_replaced(self):
        self.assertEqual(self.enrich(self.item(price=120, forward_pe=20, forward_eps=8))['scenario_eps'], 8)
        self.assertIsNone(self.enrich(self.item(price=120, forward_pe=20, forward_eps=-1))['scenario_eps'])

    def test_missing_zero_and_nonfinite_data_do_not_create_prices(self):
        for value in [None, 0, -1, float('nan'), float('inf')]:
            item = self.enrich(self.item(price=120, forward_pe=value))
            self.assertIsNone(item['scenario_eps'])
            self.assertIsNone(item['implied_eps_change'])

    def test_fcf_yield_uses_company_cap_not_position_value(self):
        item = self.enrich(self.item(free_cashflow=-20, company_market_cap=1000, market_value=10))
        self.assertEqual(item['fcf_yield'], -2)
        self.assertIsNone(self.enrich(self.item(free_cashflow=20, company_market_cap=0))['fcf_yield'])

    def test_cached_and_loss_making_company_has_explicit_notes(self):
        item = self.enrich(self.item(data_status='cached', roa=-2))
        self.assertTrue(any('快取' in note for note in item['research_notes']))
        self.assertTrue(any('ROA 為負' in note for note in item['research_notes']))
        self.assertNotIn('吸引力', item['label'])

    def test_empty_dataset_renders_as_empty(self):
        self.assertEqual(prepare_research_data({'items': []})['items'], [])


if __name__ == '__main__':
    unittest.main()
