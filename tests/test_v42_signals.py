import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from analyst_revisions import analyst_revision_score
from insider_buying import insider_buying_score
from fmp_client import FMPClient
from main_v4 import quality_liquidity_filter, recommendation_confidence
from market_breadth import market_breadth_regime
from opening_activity import _session_activity_score
from scoring import apply_reddit_blend, regime_adjusted_weights
from reddit_client import _fetch_subreddit_listing
from swing_trading import bear_case_score, swing_trading_score
from universe_builder import build_daily_universe, normalize_ticker, _valid_common_stock_symbol
from volatility_setup import volatility_setup_score
from volume_accumulation import volume_accumulation_score


class V42SignalTests(unittest.TestCase):
    def setUp(self):
        self.original_env = dict(os.environ)
        for key in (
            "FMP_API_KEY",
            "ALPHA_VANTAGE_API_KEY",
            "SEC_USER_AGENT",
            "USE_DYNAMIC_UNIVERSE",
            "MIN_PRICE",
            "MIN_AVG_DAILY_VOLUME",
            "MIN_MARKET_CAP",
            "INCLUDE_SP500",
            "INCLUDE_NASDAQ_100",
            "INCLUDE_RUSSELL_3000",
            "INCLUDE_ETF_HOLDINGS",
            "INCLUDE_REDDIT_IN_UNIVERSE",
        ):
            os.environ.pop(key, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_missing_api_keys_return_neutral(self):
        analyst = analyst_revision_score("AAPL")
        insider = insider_buying_score("AAPL")
        self.assertEqual(analyst["score"], 0.0)
        self.assertEqual(insider["score"], 0.0)

    def test_scores_stay_in_expected_ranges(self):
        df = self._price_frame()
        volume = volume_accumulation_score("TEST", df)
        volatility = volatility_setup_score("TEST", df)
        self.assertGreaterEqual(volume["score"], 0.0)
        self.assertLessEqual(volume["score"], 100.0)
        self.assertGreaterEqual(volatility["score"], 0.0)
        self.assertLessEqual(volatility["score"], 100.0)

    def test_final_weights_normalize_to_one(self):
        weights = regime_adjusted_weights("RISK_ON")
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=6)

    def test_empty_data_does_not_crash(self):
        empty = pd.DataFrame()
        malformed = pd.DataFrame({"Close": [1, 2, 3]})
        volume = volume_accumulation_score("TEST", empty)
        volatility = volatility_setup_score("TEST", empty)
        malformed_volume = volume_accumulation_score("TEST", malformed)
        malformed_volatility = volatility_setup_score("TEST", malformed)
        breadth = market_breadth_regime({"TEST": empty})
        self.assertEqual(volume["score"], 50.0)
        self.assertEqual(volatility["score"], 50.0)
        self.assertEqual(malformed_volume["score"], 50.0)
        self.assertEqual(malformed_volatility["score"], 50.0)
        self.assertEqual(breadth["regime"], "BREADTH_NEUTRAL")

    def test_reddit_blend_is_capped(self):
        row = {"ticker": "TEST", "passed_quality_filter": True, "liquidity_score": 90, "price": 25}
        blended = apply_reddit_blend(70.0, row, {"TEST": {"ticker": "TEST", "score": 100}}, enabled=True)
        self.assertEqual(blended, 75.0)

    def test_market_breadth_changes_regime(self):
        strong = {f"T{i}": self._price_frame(start=10 + i, trend=0.4) for i in range(10)}
        weak = {f"T{i}": self._price_frame(start=80 + i, trend=-0.4) for i in range(10)}
        self.assertEqual(market_breadth_regime(strong)["regime"], "BREADTH_STRONG")
        self.assertEqual(market_breadth_regime(weak)["regime"], "BREADTH_WEAK")

    def test_blank_numeric_env_uses_defaults(self):
        os.environ["MIN_STOCK_PRICE"] = ""
        os.environ["MIN_AVG_DAILY_VOLUME"] = ""
        passed, details = quality_liquidity_filter("TEST", self._price_frame(start=20, trend=0.1))
        self.assertTrue(passed)
        self.assertGreater(details["liquidity_score"], 0)

    def test_dynamic_universe_disabled_uses_manual_seed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = build_daily_universe({
                "use_dynamic_universe": False,
                "cache_dir": tmpdir,
            })
        self.assertIn("AAPL", summary["raw_universe"])
        self.assertEqual(summary["raw_universe"], summary["stage1_quality_universe"])
        self.assertEqual(summary["sources_used"]["manual_seed"], len(summary["raw_universe"]))

    def test_ticker_normalization_replaces_dot_class_symbols(self):
        self.assertEqual(normalize_ticker(" brk.b "), "BRK-B")

    def test_universe_rejects_foreign_and_otc_symbols(self):
        self.assertTrue(_valid_common_stock_symbol("BRK-B"))
        self.assertTrue(_valid_common_stock_symbol("NOW"))
        self.assertFalse(_valid_common_stock_symbol("ABBN-SW"))
        self.assertFalse(_valid_common_stock_symbol("CCO-TO"))
        self.assertFalse(_valid_common_stock_symbol("PDN-AX"))
        self.assertFalse(_valid_common_stock_symbol("APXIF"))

    def test_universe_quality_filter_keeps_liquid_names(self):
        class FakeTicker:
            fast_info = {"market_cap": 5_000_000_000}
            info = {"quoteType": "EQUITY"}

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("universe_builder._fetch_wikipedia_tickers", return_value=[]), \
                 patch("universe_builder._fetch_iwv_holdings", return_value=[]), \
                 patch("universe_builder._fetch_all_etf_holdings", return_value=[]), \
                 patch("universe_builder._fetch_reddit_tickers", return_value=[]), \
                 patch("universe_builder._fetch_earnings_calendar_symbols", return_value=[]), \
                 patch("universe_builder._collect_high_momentum_tickers", return_value=[]), \
                 patch("universe_builder.get_history", return_value=self._price_frame(start=25, trend=0.1)), \
                 patch("universe_builder.get_ticker_obj", return_value=FakeTicker()):
                summary = build_daily_universe({
                    "use_dynamic_universe": True,
                    "include_sp500": False,
                    "include_nasdaq_100": False,
                    "include_russell_3000": False,
                    "include_etf_holdings": False,
                    "include_reddit_in_universe": False,
                    "target_stage1_size": 10,
                    "cache_dir": tmpdir,
                })
        self.assertIn("AAPL", summary["stage1_quality_universe"])
        self.assertLessEqual(len(summary["stage1_quality_universe"]), 10)

    def test_reddit_fetch_falls_back_after_403(self):
        class FakeResponse:
            def __init__(self, status_code, payload=None, text=""):
                self.status_code = status_code
                self._payload = payload or {}
                self.text = text

            def json(self):
                return self._payload

        responses = [
            FakeResponse(403, text="<html>blocked</html>"),
            FakeResponse(200, payload={"data": {"children": []}}),
        ]

        with patch("reddit_client.requests.get", side_effect=responses) as mock_get:
            payload = _fetch_subreddit_listing("pennystocks", 10)

        self.assertEqual(payload, {"data": {"children": []}})
        self.assertEqual(mock_get.call_count, 2)
        self.assertIn("old.reddit.com", mock_get.call_args_list[1].args[0])

    def test_fmp_legacy_403_disables_client_for_run(self):
        class FakeResponse:
            status_code = 403
            text = '{"Error Message":"Legacy Endpoint : Due to Legacy endpoints being no longer supported"}'

            def json(self):
                return {}

        class FakeSession:
            def __init__(self):
                self.calls = 0

            def get(self, *args, **kwargs):
                self.calls += 1
                return FakeResponse()

        client = FMPClient(api_key="test")
        session = FakeSession()
        client.session = session

        self.assertIsNone(client.get("/v3/balance-sheet-statement/XYZ"))
        self.assertFalse(client.available)
        self.assertIsNone(client.get("/v4/insider-trading"))
        self.assertEqual(session.calls, 1)

    def test_extended_hours_session_score_detects_activity(self):
        df = self._intraday_frame()
        result = _session_activity_score(df, df.index[-1].date(), "04:00", "09:29", "pre_market")
        self.assertEqual(result["pre_market_data_available"], 1.0)
        self.assertGreater(result["pre_market_activity"], 50.0)
        self.assertGreater(result["pre_market_raw_return_pct"], 0.0)

    def test_swing_trading_score_returns_trade_plan(self):
        df = self._price_frame(start=20, trend=0.18)
        result = swing_trading_score(df)
        self.assertGreaterEqual(result["score"], 0.0)
        self.assertLessEqual(result["score"], 100.0)
        self.assertGreater(result["entry_price"], 0.0)
        self.assertGreater(result["target_price"], result["entry_price"])
        self.assertLess(result["stop_loss"], result["entry_price"])
        self.assertIn("reason", result)

    def test_bear_case_score_detects_breakdown(self):
        df = self._price_frame(start=80, trend=-0.25)
        result = bear_case_score(df)
        self.assertGreaterEqual(result["score"], 65.0)
        self.assertIn("reason", result)

    def test_recommendation_confidence_filters_weak_rows(self):
        weak = {
            "score": 35,
            "swing_setup": 35,
            "quality_score": 40,
            "risk_quality": 35,
            "catalyst_score": 35,
            "swing_details": {"risk_reward": 0.8},
        }
        strong = {
            "score": 78,
            "swing_setup": 82,
            "quality_score": 75,
            "risk_quality": 75,
            "catalyst_score": 70,
            "sentiment_confidence": 0.8,
            "swing_details": {"risk_reward": 2.2},
        }
        self.assertLess(recommendation_confidence(weak), 55)
        self.assertGreaterEqual(recommendation_confidence(strong), 55)

    def _price_frame(self, start=20.0, trend=0.2):
        dates = pd.date_range("2025-01-01", periods=220, freq="B")
        close = pd.Series([start + i * trend for i in range(220)], index=dates)
        if trend < 0:
            close = close.clip(lower=1)
        high = close * 1.02
        low = close * 0.98
        open_ = close.shift(1).fillna(close.iloc[0])
        volume = pd.Series([1_000_000 + i * 1000 for i in range(220)], index=dates)
        return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume})

    def _intraday_frame(self):
        rows = []
        for day, base_price, volume in [
            ("2026-05-28", 20.0, 1000),
            ("2026-05-29", 21.0, 3000),
        ]:
            for minute, price_step in [("04:00", 0.0), ("05:00", 0.2), ("09:29", 0.5)]:
                timestamp = pd.Timestamp(f"{day} {minute}", tz="America/New_York")
                close = base_price + price_step
                rows.append({
                    "timestamp": timestamp,
                    "Open": base_price,
                    "High": close * 1.01,
                    "Low": close * 0.99,
                    "Close": close,
                    "Volume": volume,
                })
        df = pd.DataFrame(rows).set_index("timestamp")
        return df


if __name__ == "__main__":
    unittest.main()
