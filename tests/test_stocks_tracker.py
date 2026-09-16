"""Tests for stocks_tracker.py's pure-Python storage/portfolio/alert layer
(Stocks Tracker pane) - no Qt involved, same split as worklog.py/
games/idle_island.py. core.config._root_override is redirected to a
scratch dir by the autouse isolated_data_dir fixture in conftest.py, so
these never touch the project's real stocks_tracker/ directory.
"""
import pytest

import stocks_tracker


def test_load_data_on_missing_file_does_not_create_directory(tmp_path):
    assert stocks_tracker.list_watchlist() == []
    assert not (tmp_path / "stocks_tracker").exists()


# ----------------------------------------------------------------------
# Watchlist
# ----------------------------------------------------------------------
def test_add_to_watchlist_then_list():
    record = stocks_tracker.add_to_watchlist("djt")
    assert record["symbol"] == "DJT"
    assert stocks_tracker.list_watchlist() == [record]


def test_add_to_watchlist_rejects_blank():
    with pytest.raises(ValueError):
        stocks_tracker.add_to_watchlist("   ")


def test_add_to_watchlist_rejects_duplicate_case_insensitively():
    stocks_tracker.add_to_watchlist("MSFT")
    with pytest.raises(ValueError):
        stocks_tracker.add_to_watchlist("msft")


def test_remove_from_watchlist():
    record = stocks_tracker.add_to_watchlist("MSFT")
    assert stocks_tracker.remove_from_watchlist(record["id"]) is True
    assert stocks_tracker.list_watchlist() == []
    assert stocks_tracker.remove_from_watchlist(record["id"]) is False


# ----------------------------------------------------------------------
# Portfolio - buy/sell/summary/reset
# ----------------------------------------------------------------------
def test_buy_stock_deducts_cash_and_creates_a_holding():
    txn = stocks_tracker.buy_stock("MSFT", 10, 100.0)
    assert txn["side"] == "buy"
    assert txn["amount"] == 1000.0
    data = stocks_tracker.load_data()
    assert data["portfolio"]["cash"] == stocks_tracker.DEFAULT_STARTING_CASH - 1000.0
    assert data["portfolio"]["holdings"] == [{"symbol": "MSFT", "shares": 10.0, "avg_cost": 100.0}]


def test_buy_stock_averages_cost_basis_across_two_lots():
    stocks_tracker.buy_stock("MSFT", 10, 100.0)
    stocks_tracker.buy_stock("MSFT", 10, 200.0)
    holding = stocks_tracker.load_data()["portfolio"]["holdings"][0]
    assert holding["shares"] == 20.0
    assert holding["avg_cost"] == pytest.approx(150.0)


def test_buy_stock_rejects_non_positive_shares_or_price():
    with pytest.raises(ValueError):
        stocks_tracker.buy_stock("MSFT", 0, 100.0)
    with pytest.raises(ValueError):
        stocks_tracker.buy_stock("MSFT", 10, 0)


def test_buy_stock_rejects_insufficient_cash():
    with pytest.raises(ValueError):
        stocks_tracker.buy_stock("MSFT", 1_000_000, 1000.0)


def test_sell_stock_computes_realized_pnl_and_reduces_shares():
    stocks_tracker.buy_stock("MSFT", 10, 100.0)
    txn = stocks_tracker.sell_stock("MSFT", 4, 150.0)
    assert txn["realized_pnl"] == pytest.approx(200.0)
    holding = stocks_tracker.load_data()["portfolio"]["holdings"][0]
    assert holding["shares"] == 6.0


def test_sell_stock_removes_holding_when_fully_sold():
    stocks_tracker.buy_stock("MSFT", 10, 100.0)
    stocks_tracker.sell_stock("MSFT", 10, 150.0)
    assert stocks_tracker.load_data()["portfolio"]["holdings"] == []


def test_sell_stock_rejects_overselling_or_no_holding():
    with pytest.raises(ValueError):
        stocks_tracker.sell_stock("MSFT", 1, 100.0)
    stocks_tracker.buy_stock("MSFT", 5, 100.0)
    with pytest.raises(ValueError):
        stocks_tracker.sell_stock("MSFT", 10, 100.0)


def test_portfolio_summary_reports_none_not_zero_for_a_failed_quote():
    stocks_tracker.buy_stock("MSFT", 10, 100.0)
    summary = stocks_tracker.portfolio_summary({"MSFT": None})
    holding = summary["holdings"][0]
    assert holding["price"] is None
    assert holding["market_value"] is None
    assert holding["unrealized_pnl"] is None
    assert summary["total_equity"] is None
    assert summary["total_unrealized_pnl"] is None


def test_portfolio_summary_computes_totals_when_fully_priced():
    stocks_tracker.buy_stock("MSFT", 10, 100.0)
    summary = stocks_tracker.portfolio_summary({"MSFT": 150.0})
    assert summary["holdings"][0]["market_value"] == 1500.0
    assert summary["holdings"][0]["unrealized_pnl"] == 500.0
    assert summary["total_unrealized_pnl"] == 500.0
    assert summary["total_equity"] == summary["cash"] + 1500.0


def test_portfolio_summary_tracks_realized_pnl_across_sells():
    stocks_tracker.buy_stock("MSFT", 10, 100.0)
    stocks_tracker.sell_stock("MSFT", 10, 150.0)
    summary = stocks_tracker.portfolio_summary({})
    assert summary["total_realized_pnl"] == pytest.approx(500.0)


def test_reset_portfolio_wipes_state_and_resets_cash():
    stocks_tracker.buy_stock("MSFT", 10, 100.0)
    stocks_tracker.reset_portfolio(starting_cash=5000.0)
    data = stocks_tracker.load_data()
    assert data["portfolio"]["cash"] == 5000.0
    assert data["portfolio"]["starting_cash"] == 5000.0
    assert data["portfolio"]["holdings"] == []
    assert data["transactions"] == []


# ----------------------------------------------------------------------
# Alerts
# ----------------------------------------------------------------------
def test_check_alert_fires_once_then_dedupes_until_another_increment():
    fired, state = stocks_tracker.check_alert("MSFT", 106.0, 100.0, 5.0, None)
    assert fired is True
    assert state["direction"] == "up"

    fired, state = stocks_tracker.check_alert("MSFT", 108.0, 100.0, 5.0, state)
    assert fired is False

    fired, state = stocks_tracker.check_alert("MSFT", 112.0, 100.0, 5.0, state)
    assert fired is True


def test_check_alert_clears_state_on_recovery_allowing_a_future_realert():
    fired, state = stocks_tracker.check_alert("MSFT", 106.0, 100.0, 5.0, None)
    assert fired is True

    fired, state = stocks_tracker.check_alert("MSFT", 101.0, 100.0, 5.0, state)
    assert fired is False
    assert state is None

    fired, state = stocks_tracker.check_alert("MSFT", 106.0, 100.0, 5.0, state)
    assert fired is True


def test_check_alert_fires_again_on_direction_reversal():
    fired, state = stocks_tracker.check_alert("MSFT", 106.0, 100.0, 5.0, None)
    assert fired is True
    fired, state = stocks_tracker.check_alert("MSFT", 93.0, 100.0, 5.0, state)
    assert fired is True
    assert state["direction"] == "down"


def test_evaluate_alerts_skips_a_symbol_with_a_failed_quote():
    data = stocks_tracker.load_data()
    fired = stocks_tracker.evaluate_alerts({"MSFT": None}, data)
    assert fired == []
    assert data["alert_state"] == {}


def test_evaluate_alerts_fires_and_persists_alert_state():
    data = stocks_tracker.load_data()
    fired = stocks_tracker.evaluate_alerts(
        {"MSFT": {"price": 106.0, "previous_close": 100.0}}, data,
    )
    assert len(fired) == 1
    assert fired[0]["symbol"] == "MSFT"
    assert fired[0]["direction"] == "up"
    persisted = stocks_tracker.load_data()
    assert persisted["alert_state"]["MSFT"]["last_alerted_price"] == 106.0
