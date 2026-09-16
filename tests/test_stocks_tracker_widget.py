"""Widget-wiring tests for StocksTrackerWidget - button click -> worker ->
UI/state update. Constructs StocksTrackerWidget directly rather than the
full WebAgentGUI (unlike test_gui_pages.py's `gui` fixture): building the
whole app pulls in WeatherStationWidget, whose real background
tile-fetch/network QThreads accumulate across the many WebAgentGUI
instances that file's test suite constructs and crash the interpreter after
~10 of them (confirmed live to happen identically with Stocks Tracker
completely absent from the nav - a pre-existing environment issue, not
something introduced here). Testing this widget in isolation avoids that
entirely while still covering the same button-click -> worker -> UI wiring
test_gui_pages.py's existing tests do for other panes.

Same offscreen discipline as test_gui_pages.py: QT_QPA_PLATFORM=offscreen,
never calls app.exec().
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox

import stocks_tracker
import webagent
from stocks_tracker import StocksTrackerWidget


@pytest.fixture(scope="module")
def qapp():
    try:
        return QApplication.instance() or QApplication([])
    except Exception as exc:
        pytest.skip(f"Qt platform plugin could not initialize headlessly: {exc}")


@pytest.fixture
def widget(qapp, isolated_data_dir):
    w = StocksTrackerWidget()
    yield w
    w.close()
    w.deleteLater()


def test_adding_a_watchlist_ticker_shows_up_after_refresh(widget, qapp, monkeypatch):
    monkeypatch.setattr(stocks_tracker, "resolve_ticker", lambda text: ("DJT", {"price": 20.0, "previous_close": 19.0}))
    widget.watchlist_input.setText("djt")

    widget._add_watchlist_clicked()
    widget._watchlist_add_worker.wait(2000)
    qapp.processEvents()

    assert [w["symbol"] for w in stocks_tracker.list_watchlist()] == ["DJT"]
    assert widget.watchlist_input.text() == ""


def test_adding_a_watchlist_ticker_shows_an_error_on_failed_resolution(widget, qapp, monkeypatch):
    monkeypatch.setattr(stocks_tracker, "resolve_ticker", lambda text: None)
    widget.watchlist_input.setText("nonexistent")

    widget._add_watchlist_clicked()
    widget._watchlist_add_worker.wait(2000)
    qapp.processEvents()

    assert stocks_tracker.list_watchlist() == []
    assert "nonexistent" in widget.watchlist_status_label.text()


def test_buy_updates_holdings_and_cash(widget, qapp, monkeypatch):
    monkeypatch.setattr(
        webagent, "_fetch_stock_quote",
        lambda symbol: {"symbol": symbol, "price": 50.0, "currency": "USD", "previous_close": 48.0,
                         "day_high": 51, "day_low": 49, "exchange": "NYSE", "observed_at": None},
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    widget.trade_symbol_input.setText("MSFT")
    widget.trade_shares_input.setValue(2)

    widget._trade_clicked("buy")
    widget._trade_worker.wait(2000)
    qapp.processEvents()

    data = stocks_tracker.load_data()
    assert data["portfolio"]["holdings"] == [{"symbol": "MSFT", "shares": 2.0, "avg_cost": 50.0}]
    assert data["portfolio"]["cash"] == stocks_tracker.DEFAULT_STARTING_CASH - 100.0


def test_buy_declined_at_confirm_dialog_does_nothing(widget, qapp, monkeypatch):
    monkeypatch.setattr(
        webagent, "_fetch_stock_quote",
        lambda symbol: {"symbol": symbol, "price": 50.0, "currency": "USD", "previous_close": 48.0,
                         "day_high": 51, "day_low": 49, "exchange": "NYSE", "observed_at": None},
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    widget.trade_symbol_input.setText("MSFT")
    widget.trade_shares_input.setValue(2)

    widget._trade_clicked("buy")
    widget._trade_worker.wait(2000)
    qapp.processEvents()

    assert stocks_tracker.load_data()["portfolio"]["holdings"] == []


def test_reset_portfolio_confirmed_wipes_state(widget, qapp, monkeypatch):
    stocks_tracker.buy_stock("MSFT", 2, 50.0)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QInputDialog, "getDouble", staticmethod(lambda *a, **k: (2500.0, True)))

    widget._reset_portfolio_clicked()

    data = stocks_tracker.load_data()
    assert data["portfolio"]["holdings"] == []
    assert data["portfolio"]["cash"] == 2500.0


def test_reset_portfolio_declined_does_nothing(widget, qapp, monkeypatch):
    stocks_tracker.buy_stock("MSFT", 2, 50.0)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)

    widget._reset_portfolio_clicked()

    assert stocks_tracker.load_data()["portfolio"]["holdings"] != []
