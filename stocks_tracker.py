"""Stocks Tracker pane: a USA-focused watchlist with live quotes, a
simulated ("paper trading") portfolio, big-mover alerts, and two "other
investor patterns" feeds - Senate trading disclosures (stocks_congress.py)
and notable investors' 13F institutional holdings (stocks_13f.py).

Split the same way as worklog.py/games/idle_island.py: plain-Python
storage/logic up top (no Qt imports, unit-testable on its own) with
StocksTrackerWidget's Qt layer below it as a thin UI over that state. All
watchlist/portfolio/alert state lives in one JSON file under
core_config.path("stocks_tracker") - same lazy-mkdir-on-write-only
discipline as worklog.py: a read must never create the directory. Every
mutation writes through immediately (no autosave timer, no save_now()).

Quotes reuse webagent._fetch_stock_quote/_resolve_stock_symbol (keyless
Yahoo Finance) - no new dependency, no API key. No quote is ever persisted:
every tab re-fetches live on open/refresh, and a failed fetch surfaces as
an explicit None/error rather than a stale or fabricated number (see
MEMORY: "No silent fallbacks").
"""
import json
import os
import uuid
from datetime import datetime

import webagent
import stocks_13f
import stocks_congress
from core import config as core_config

DEFAULT_STARTING_CASH = 100000.0
# Matches worklog.STATUS_COLORS's Hold/Done colors, so an "alert" reads
# consistently with the rest of the app rather than introducing new hues.
MOVE_UP_COLOR = "#3ecf8e"
MOVE_DOWN_COLOR = "#e5484d"


# ----------------------------------------------------------------------
# Storage - one JSON file: watchlist, portfolio, transactions, alerts
# ----------------------------------------------------------------------
def _data_path():
    return os.path.join(core_config.path("stocks_tracker"), "stocks_tracker.json")


def _new_id():
    return uuid.uuid4().hex[:8]


def _default_data():
    return {
        "watchlist": [],
        "portfolio": {"starting_cash": DEFAULT_STARTING_CASH, "cash": DEFAULT_STARTING_CASH, "holdings": []},
        "transactions": [],
        "alert_settings": {"threshold_pct": 5.0, "sound_enabled": True, "auto_refresh_minutes": 5},
        "alert_state": {},
        "column_settings": {},
    }


def load_data():
    path = _data_path()
    if not os.path.isfile(path):
        return _default_data()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return _default_data()
    if not isinstance(data, dict):
        return _default_data()
    defaults = _default_data()
    data.setdefault("watchlist", defaults["watchlist"])
    data.setdefault("portfolio", defaults["portfolio"])
    data.setdefault("transactions", defaults["transactions"])
    data.setdefault("alert_settings", defaults["alert_settings"])
    data.setdefault("alert_state", defaults["alert_state"])
    data.setdefault("column_settings", defaults["column_settings"])
    data["portfolio"].setdefault("starting_cash", DEFAULT_STARTING_CASH)
    data["portfolio"].setdefault("cash", data["portfolio"]["starting_cash"])
    data["portfolio"].setdefault("holdings", [])
    data["alert_settings"].setdefault("threshold_pct", 5.0)
    data["alert_settings"].setdefault("sound_enabled", True)
    data["alert_settings"].setdefault("auto_refresh_minutes", 5)
    return data


def save_data(data):
    path = _data_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ----------------------------------------------------------------------
# Quotes - thin wrappers over webagent's existing keyless Yahoo Finance
# fetchers, so this module never talks to a quote API directly.
# ----------------------------------------------------------------------
def resolve_ticker(text):
    """Given raw user input (a ticker or a company name), returns
    (symbol, quote) - tries it as a ticker first (one request), falling
    back to name resolution only if that fails (a second request). Returns
    None if neither resolves. Does real network I/O - callers on the GUI
    thread must run this inside a worker."""
    text = (text or "").strip()
    if not text:
        return None
    symbol_guess = text.upper()
    quote = webagent._fetch_stock_quote(symbol_guess)
    if quote is not None:
        return symbol_guess, quote
    resolved = webagent._resolve_stock_symbol(text)
    if resolved is None:
        return None
    symbol, _display_name = resolved
    quote = webagent._fetch_stock_quote(symbol)
    if quote is None:
        return None
    return symbol, quote


def fetch_quotes(symbols):
    """symbols: iterable of ticker strings. -> {symbol: quote_dict|None}.
    One request per symbol - Yahoo's chart endpoint has no batch form."""
    return {symbol: webagent._fetch_stock_quote(symbol) for symbol in symbols}


def quotes_to_prices(quotes):
    """{symbol: quote_dict|None} -> {symbol: price|None} - portfolio_summary
    only needs the price, not the whole quote."""
    return {symbol: (quote.get("price") if quote else None) for symbol, quote in quotes.items()}


# ----------------------------------------------------------------------
# Watchlist
# ----------------------------------------------------------------------
def list_watchlist():
    return load_data()["watchlist"]


def add_to_watchlist(symbol):
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("Enter a ticker symbol.")
    data = load_data()
    if any(w["symbol"] == symbol for w in data["watchlist"]):
        raise ValueError(f'"{symbol}" is already on the watchlist.')
    record = {"id": _new_id(), "symbol": symbol, "added_at": datetime.now().isoformat()}
    data["watchlist"].append(record)
    save_data(data)
    return record


def remove_from_watchlist(entry_id):
    data = load_data()
    remaining = [w for w in data["watchlist"] if w["id"] != entry_id]
    if len(remaining) == len(data["watchlist"]):
        return False
    data["watchlist"] = remaining
    save_data(data)
    return True


# ----------------------------------------------------------------------
# Portfolio (paper trading)
# ----------------------------------------------------------------------
def buy_stock(symbol, shares, price):
    """Caller fetches the live quote first and passes price in, so this
    stays synchronously unit-testable with no network mock. avg_cost is a
    weighted average across old + new lots."""
    symbol = (symbol or "").strip().upper()
    shares = float(shares)
    price = float(price)
    if not symbol:
        raise ValueError("Enter a ticker symbol.")
    if shares <= 0:
        raise ValueError("Shares must be positive.")
    if price <= 0:
        raise ValueError("Price must be positive.")
    data = load_data()
    cost = shares * price
    if cost > data["portfolio"]["cash"] + 1e-9:
        raise ValueError(f"Insufficient cash: need ${cost:,.2f}, have ${data['portfolio']['cash']:,.2f}.")
    holdings = data["portfolio"]["holdings"]
    holding = next((h for h in holdings if h["symbol"] == symbol), None)
    if holding is None:
        holdings.append({"symbol": symbol, "shares": shares, "avg_cost": price})
    else:
        total_shares = holding["shares"] + shares
        holding["avg_cost"] = (holding["avg_cost"] * holding["shares"] + price * shares) / total_shares
        holding["shares"] = total_shares
    data["portfolio"]["cash"] -= cost
    transaction = {
        "id": _new_id(), "symbol": symbol, "side": "buy", "shares": shares, "price": price,
        "amount": cost, "realized_pnl": None, "at": datetime.now().isoformat(),
    }
    data["transactions"].append(transaction)
    save_data(data)
    return transaction


def sell_stock(symbol, shares, price):
    """realized_pnl = (price - avg_cost) * shares. Removes the holding
    entirely once its shares round to zero."""
    symbol = (symbol or "").strip().upper()
    shares = float(shares)
    price = float(price)
    if shares <= 0:
        raise ValueError("Shares must be positive.")
    if price <= 0:
        raise ValueError("Price must be positive.")
    data = load_data()
    holdings = data["portfolio"]["holdings"]
    holding = next((h for h in holdings if h["symbol"] == symbol), None)
    if holding is None:
        raise ValueError(f'No holding in "{symbol}" to sell.')
    if shares > holding["shares"] + 1e-9:
        raise ValueError(f'Only holding {holding["shares"]:g} shares of "{symbol}".')
    proceeds = shares * price
    realized_pnl = (price - holding["avg_cost"]) * shares
    holding["shares"] -= shares
    if holding["shares"] <= 1e-9:
        holdings.remove(holding)
    data["portfolio"]["cash"] += proceeds
    transaction = {
        "id": _new_id(), "symbol": symbol, "side": "sell", "shares": shares, "price": price,
        "amount": proceeds, "realized_pnl": realized_pnl, "at": datetime.now().isoformat(),
    }
    data["transactions"].append(transaction)
    save_data(data)
    return transaction


def list_transactions():
    return load_data()["transactions"]


def portfolio_summary(current_prices):
    """current_prices: {symbol: price|None}. A holding whose price is None
    (quote failed) reports market_value=None/unrealized_pnl=None, and the
    aggregate totals report None too rather than a partial sum that would
    silently misrepresent the whole portfolio's value."""
    data = load_data()
    portfolio = data["portfolio"]
    holdings_out = []
    total_market_value = 0.0
    total_unrealized = 0.0
    all_priced = True
    for holding in portfolio["holdings"]:
        price = current_prices.get(holding["symbol"])
        if price is None:
            all_priced = False
            holdings_out.append({**holding, "price": None, "market_value": None, "unrealized_pnl": None})
            continue
        market_value = holding["shares"] * price
        unrealized = (price - holding["avg_cost"]) * holding["shares"]
        holdings_out.append({**holding, "price": price, "market_value": market_value, "unrealized_pnl": unrealized})
        total_market_value += market_value
        total_unrealized += unrealized
    total_realized = sum(t["realized_pnl"] for t in data["transactions"] if t["realized_pnl"] is not None)
    return {
        "holdings": holdings_out,
        "cash": portfolio["cash"],
        "total_equity": (portfolio["cash"] + total_market_value) if all_priced else None,
        "total_unrealized_pnl": total_unrealized if all_priced else None,
        "total_realized_pnl": total_realized,
    }


def reset_portfolio(starting_cash=None):
    """Wipes holdings+transactions, resets cash to starting_cash (or the
    already-configured value). Confirm-dialog gating belongs to the caller."""
    data = load_data()
    if starting_cash is not None:
        data["portfolio"]["starting_cash"] = float(starting_cash)
    data["portfolio"]["cash"] = data["portfolio"]["starting_cash"]
    data["portfolio"]["holdings"] = []
    data["transactions"] = []
    save_data(data)


# ----------------------------------------------------------------------
# Big-mover alerts
# ----------------------------------------------------------------------
def get_alert_settings():
    return load_data()["alert_settings"]


def set_alert_settings(threshold_pct=None, sound_enabled=None, auto_refresh_minutes=None):
    data = load_data()
    settings = data["alert_settings"]
    if threshold_pct is not None:
        settings["threshold_pct"] = float(threshold_pct)
    if sound_enabled is not None:
        settings["sound_enabled"] = bool(sound_enabled)
    if auto_refresh_minutes is not None:
        settings["auto_refresh_minutes"] = float(auto_refresh_minutes)
    save_data(data)
    return settings


def check_alert(symbol, price, previous_close, threshold_pct, state):
    """Pure, no I/O. `state` is the caller's alert_state.get(symbol) (or
    None). Returns (fired, new_state) - new_state is what the caller should
    store back (None means "clear this symbol's entry").

    Below threshold: clears any existing state, so a later re-cross alerts
    again (recovery resets). At/above threshold: fires if there's no prior
    state, the direction reversed, or price has moved another full
    threshold-increment past the last-alerted price in the same direction;
    otherwise stays silent (already alerted for this move)."""
    if not previous_close:
        return False, state
    pct_change = (price - previous_close) / previous_close * 100
    if abs(pct_change) < threshold_pct:
        return False, None
    direction = "up" if pct_change > 0 else "down"
    if state is None or state.get("direction") != direction:
        fired = True
    else:
        last_price = state.get("last_alerted_price") or previous_close
        moved_further_pct = abs(price - last_price) / abs(last_price) * 100 if last_price else 0.0
        fired = moved_further_pct >= threshold_pct
    if not fired:
        return False, state
    return True, {"last_alerted_price": price, "direction": direction, "last_alerted_at": datetime.now().isoformat()}


def evaluate_alerts(quotes, data):
    """quotes: {symbol: quote_dict|None} for the union of watchlist and
    portfolio-holding symbols. Skips a None quote - a failed fetch isn't a
    "big move". Mutates+saves data["alert_state"]; returns the list of
    alerts fired this call: [{"symbol","direction","pct_change","price"}]."""
    threshold_pct = data["alert_settings"]["threshold_pct"]
    alert_state = data["alert_state"]
    fired_alerts = []
    for symbol, quote in quotes.items():
        if quote is None:
            continue
        price = quote.get("price")
        previous_close = quote.get("previous_close")
        if price is None or previous_close is None:
            continue
        fired, new_state = check_alert(symbol, price, previous_close, threshold_pct, alert_state.get(symbol))
        if new_state is None:
            alert_state.pop(symbol, None)
        else:
            alert_state[symbol] = new_state
        if fired:
            pct_change = (price - previous_close) / previous_close * 100
            fired_alerts.append({"symbol": symbol, "direction": new_state["direction"], "pct_change": pct_change, "price": price})
    save_data(data)
    return fired_alerts


# ----------------------------------------------------------------------
# Widget
# ----------------------------------------------------------------------
from PyQt6.QtCore import QThread, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDoubleSpinBox, QFrame, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

import worklog_audio


class _FetchWorker(QThread):
    """Runs one zero-arg callable off the GUI thread - same shape as
    weather_station.py's own _FetchWorker, duplicated locally so this
    module doesn't have to import the GUI module."""
    result_ready = pyqtSignal(object)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        self.result_ready.emit(self.fn())


def _column_settings(table_key):
    """Normalizes column_settings[table_key] to {"hidden": [...], "widths":
    {label: px}}. Older saves may hold a bare list (hidden labels only, from
    before width persistence existed) - treat that as hidden with no
    widths rather than discarding it."""
    raw = load_data()["column_settings"].get(table_key, {})
    if isinstance(raw, list):
        return {"hidden": raw, "widths": {}}
    return {"hidden": raw.get("hidden", []), "widths": raw.get("widths", {})}


def _configure_table(table, headers, table_key=None):
    """All columns start Interactive (user-draggable) rather than one forced
    Stretch column, so every column - including whichever one used to be
    forced wide - can be resized by hand. Initial widths come from the
    header text via resizeColumnsToContents(), then overridden by any saved
    widths; refresh methods must not call resizeColumnsToContents() again,
    or a user's manual resize would get reset on every refresh.

    Also wires a right-click menu on the header for showing/hiding columns,
    and (when table_key is given) persists hidden-column and width choices
    to stocks_tracker.json under column_settings[table_key], restoring them
    here - refresh methods that call this every time otherwise reset both
    along with the rest of the table."""
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.resizeColumnsToContents()
    if table_key:
        settings = _column_settings(table_key)
        hidden_labels = set(settings["hidden"])
        widths = settings["widths"]
        for col, label in enumerate(headers):
            if label in hidden_labels:
                table.setColumnHidden(col, True)
            if label in widths:
                table.setColumnWidth(col, widths[label])
    _add_column_visibility_menu(table, headers, table_key)
    if table_key:
        _wire_column_width_saving(table, headers, table_key)


def _wire_column_width_saving(table, headers, table_key):
    """Persists manual column-width drags. Writes through on every resize
    (same immediate-write discipline as the rest of this module - see
    module docstring) rather than debouncing, so a resize followed by
    closing the app right away isn't lost waiting on a timer that never
    fires."""
    header = table.horizontalHeader()

    def on_resized(logical_index, _old_size, new_size):
        if logical_index >= len(headers):
            return
        label = headers[logical_index]
        if not label or table.isColumnHidden(logical_index):
            return
        data = load_data()
        settings = data["column_settings"].setdefault(table_key, {})
        if isinstance(settings, list):
            settings = {"hidden": settings, "widths": {}}
            data["column_settings"][table_key] = settings
        settings.setdefault("widths", {})[label] = new_size
        save_data(data)

    header.sectionResized.connect(on_resized)


def _add_column_visibility_menu(table, headers, table_key=None):
    header = table.horizontalHeader()
    header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def set_hidden(col, label, hidden):
        table.setColumnHidden(col, hidden)
        if not table_key or not label:
            return
        data = load_data()
        settings = data["column_settings"].setdefault(table_key, {})
        if isinstance(settings, list):
            settings = {"hidden": settings, "widths": {}}
            data["column_settings"][table_key] = settings
        hidden_labels = set(settings.get("hidden", []))
        if hidden:
            hidden_labels.add(label)
        else:
            hidden_labels.discard(label)
        settings["hidden"] = sorted(hidden_labels)
        save_data(data)

    def show_menu(pos):
        menu = QMenu(table)
        for col, label in enumerate(headers):
            action = menu.addAction(label or f"Column {col + 1}")
            action.setCheckable(True)
            action.setChecked(not table.isColumnHidden(col))
            action.toggled.connect(lambda checked, c=col, l=label: set_hidden(c, l, not checked))
        menu.exec(header.mapToGlobal(pos))

    header.customContextMenuRequested.connect(show_menu)


def _money(value):
    return f"${value:,.2f}" if value is not None else "N/A"


def _pct(value):
    return f"{value:+.2f}%" if value is not None else "N/A"


class StocksTrackerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._investor_cache = {}
        self._congress_cookies = None
        self._congress_csrf_token = None
        self._congress_filings = []
        self._sound_player = worklog_audio.SoundPlayer()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(15, 15, 15, 15)
        outer.setSpacing(10)

        header_row = QHBoxLayout()
        title = QLabel("📈 Stocks Tracker")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        header_row.addWidget(title)
        header_row.addStretch()
        outer.addLayout(header_row)

        self.alert_banner_label = QLabel("")
        self.alert_banner_label.setWordWrap(True)
        self.alert_banner_label.setStyleSheet("color: #f5a524; font-weight: bold;")
        outer.addWidget(self.alert_banner_label)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        self.watchlist_tab = self._build_watchlist_tab()
        self.portfolio_tab = self._build_portfolio_tab()
        self.congress_tab = self._build_congress_tab()
        self.investors_tab = self._build_investors_tab()
        self.settings_tab = self._build_settings_tab()
        self.tabs.addTab(self.watchlist_tab, "Watchlist")
        self.tabs.addTab(self.portfolio_tab, "Portfolio")
        self.tabs.addTab(self.congress_tab, "Congress")
        self.tabs.addTab(self.investors_tab, "Notable Investors")
        self.tabs.addTab(self.settings_tab, "⚙️ Settings")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._auto_refresh_tick)
        self._apply_refresh_interval()

        self._refresh_watchlist()
        self._refresh_portfolio()

    def _on_tab_changed(self, index):
        widget = self.tabs.widget(index)
        if widget is self.watchlist_tab:
            self._refresh_watchlist()
        elif widget is self.portfolio_tab:
            self._refresh_portfolio()

    def _apply_refresh_interval(self):
        minutes = get_alert_settings()["auto_refresh_minutes"]
        self.refresh_timer.start(max(1, int(minutes * 60_000)))

    # ------------------------------------------------------------------
    # Shared: which symbols need a quote, and the alert check every
    # refresh (manual or timer-driven) runs against them.
    # ------------------------------------------------------------------
    def _tracked_symbols(self):
        symbols = {w["symbol"] for w in list_watchlist()}
        symbols.update(h["symbol"] for h in load_data()["portfolio"]["holdings"])
        return sorted(symbols)

    def _run_alert_check(self, quotes):
        data = load_data()
        fired = evaluate_alerts(quotes, data)
        if not fired:
            return
        settings = data["alert_settings"]
        parts = []
        for alert in fired:
            arrow = "▲" if alert["direction"] == "up" else "▼"
            parts.append(f"{alert['symbol']} {arrow} {alert['pct_change']:+.1f}% (${alert['price']:,.2f})")
        self.alert_banner_label.setText("Big movers: " + " | ".join(parts))
        if settings["sound_enabled"]:
            self._sound_player.play_once("bell")

    def _auto_refresh_tick(self):
        symbols = self._tracked_symbols()
        if not symbols:
            return

        def work():
            return fetch_quotes(symbols)

        def handle(quotes):
            self._run_alert_check(quotes)
            self._refresh_watchlist_table(quotes)
            if self.tabs.currentWidget() is self.portfolio_tab:
                self._refresh_portfolio()

        worker = _FetchWorker(work)
        worker.result_ready.connect(handle)
        self._auto_refresh_worker = worker
        worker.start()

    # ------------------------------------------------------------------
    # Watchlist
    # ------------------------------------------------------------------
    def _build_watchlist_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        add_row = QHBoxLayout()
        self.watchlist_input = QLineEdit()
        self.watchlist_input.setPlaceholderText('Ticker or company name, e.g. "DJT" or "Trump Media"')
        self.watchlist_input.returnPressed.connect(self._add_watchlist_clicked)
        add_row.addWidget(self.watchlist_input, 1)
        add_button = QPushButton("+ Add")
        add_button.clicked.connect(self._add_watchlist_clicked)
        add_row.addWidget(add_button)
        refresh_button = QPushButton("↻ Refresh")
        refresh_button.clicked.connect(self._refresh_watchlist)
        add_row.addWidget(refresh_button)
        layout.addLayout(add_row)

        self.watchlist_status_label = QLabel("")
        layout.addWidget(self.watchlist_status_label)

        self.watchlist_table = QTableWidget(0, 9)
        _configure_table(
            self.watchlist_table,
            ["Ticker", "Name", "Price", "Chg", "Chg %", "Day High", "Day Low", "Exchange", ""],
            table_key="watchlist",
        )
        layout.addWidget(self.watchlist_table, 1)
        return page

    def _add_watchlist_clicked(self):
        text = self.watchlist_input.text().strip()
        if not text:
            self.watchlist_status_label.setText("Enter a ticker or company name.")
            return
        self.watchlist_status_label.setText(f'Looking up "{text}"...')

        def work():
            return resolve_ticker(text)

        def handle(resolved):
            if resolved is None:
                self.watchlist_status_label.setText(f'Could not find a stock matching "{text}".')
                return
            symbol, _quote = resolved
            try:
                add_to_watchlist(symbol)
            except ValueError as exc:
                self.watchlist_status_label.setText(str(exc))
                return
            self.watchlist_input.clear()
            self.watchlist_status_label.setText(f'Added "{symbol}".')
            self._refresh_watchlist()

        worker = _FetchWorker(work)
        worker.result_ready.connect(handle)
        self._watchlist_add_worker = worker
        worker.start()

    def _refresh_watchlist(self):
        entries = list_watchlist()
        if not entries:
            self.watchlist_table.setRowCount(0)
            self.watchlist_status_label.setText("Watchlist is empty - add a ticker above.")
            return
        self.watchlist_status_label.setText("Loading quotes...")
        symbols = [w["symbol"] for w in entries]

        def work():
            return fetch_quotes(symbols)

        def handle(quotes):
            self.watchlist_status_label.setText("")
            self._refresh_watchlist_table(quotes)
            self._run_alert_check(quotes)

        worker = _FetchWorker(work)
        worker.result_ready.connect(handle)
        self._watchlist_worker = worker
        worker.start()

    def _refresh_watchlist_table(self, quotes):
        entries = list_watchlist()
        threshold_pct = get_alert_settings()["threshold_pct"]
        self.watchlist_table.setRowCount(len(entries))
        pct_col = 4
        for row, entry in enumerate(entries):
            symbol = entry["symbol"]
            quote = quotes.get(symbol)
            values = [symbol]
            color = None
            pct_change = None
            if quote is None:
                values += ["N/A", "N/A", "N/A", "N/A", "N/A", "N/A", "N/A"]
            else:
                price = quote.get("price")
                previous_close = quote.get("previous_close")
                change = (price - previous_close) if (price is not None and previous_close) else None
                pct_change = (change / previous_close * 100) if (change is not None and previous_close) else None
                values += [
                    quote.get("name") or "N/A",
                    _money(price), _money(change), _pct(pct_change),
                    _money(quote.get("day_high")), _money(quote.get("day_low")), quote.get("exchange") or "N/A",
                ]
                if pct_change is not None and abs(pct_change) >= threshold_pct:
                    color = QColor(MOVE_UP_COLOR if pct_change > 0 else MOVE_DOWN_COLOR)
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if color is not None:
                    item.setBackground(color)
                if col == pct_col and pct_change is not None and color is None:
                    item.setForeground(QColor(MOVE_UP_COLOR if pct_change > 0 else MOVE_DOWN_COLOR))
                self.watchlist_table.setItem(row, col, item)
            remove_button = QPushButton("✕")
            remove_button.setFixedWidth(28)
            remove_button.clicked.connect(lambda _checked=False, entry_id=entry["id"]: self._remove_watchlist_clicked(entry_id))
            self.watchlist_table.setCellWidget(row, 8, remove_button)

    def _remove_watchlist_clicked(self, entry_id):
        remove_from_watchlist(entry_id)
        self._refresh_watchlist()

    # ------------------------------------------------------------------
    # Portfolio (paper trading)
    # ------------------------------------------------------------------
    def _build_portfolio_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        summary_row = QHBoxLayout()
        self.cash_label = QLabel("Cash: -")
        self.equity_label = QLabel("Total Equity: -")
        self.unrealized_label = QLabel("Unrealized P&L: -")
        self.realized_label = QLabel("Realized P&L: -")
        for label in (self.cash_label, self.equity_label, self.unrealized_label, self.realized_label):
            label.setStyleSheet("font-weight: bold;")
            summary_row.addWidget(label)
        summary_row.addStretch()
        refresh_button = QPushButton("↻ Refresh")
        refresh_button.clicked.connect(self._refresh_portfolio)
        summary_row.addWidget(refresh_button)
        layout.addLayout(summary_row)

        trade_row = QHBoxLayout()
        self.trade_symbol_input = QLineEdit()
        self.trade_symbol_input.setPlaceholderText("Ticker")
        self.trade_symbol_input.setFixedWidth(100)
        trade_row.addWidget(self.trade_symbol_input)
        self.trade_shares_input = QDoubleSpinBox()
        self.trade_shares_input.setDecimals(4)
        self.trade_shares_input.setRange(0.0001, 1_000_000)
        self.trade_shares_input.setValue(1)
        trade_row.addWidget(QLabel("Shares:"))
        trade_row.addWidget(self.trade_shares_input)
        buy_button = QPushButton("Buy")
        buy_button.clicked.connect(lambda: self._trade_clicked("buy"))
        trade_row.addWidget(buy_button)
        sell_button = QPushButton("Sell")
        sell_button.clicked.connect(lambda: self._trade_clicked("sell"))
        trade_row.addWidget(sell_button)
        trade_row.addStretch()
        reset_button = QPushButton("⚠ Reset Simulation")
        reset_button.clicked.connect(self._reset_portfolio_clicked)
        trade_row.addWidget(reset_button)
        layout.addLayout(trade_row)

        self.portfolio_status_label = QLabel("")
        layout.addWidget(self.portfolio_status_label)

        layout.addWidget(QLabel("Holdings"))
        self.holdings_table = QTableWidget(0, 6)
        _configure_table(self.holdings_table, ["Symbol", "Shares", "Avg Cost", "Price", "Market Value", "Unrealized P&L"], table_key="holdings")
        layout.addWidget(self.holdings_table, 1)

        layout.addWidget(QLabel("Transactions"))
        self.transactions_table = QTableWidget(0, 7)
        _configure_table(self.transactions_table, ["Date", "Symbol", "Side", "Shares", "Price", "Amount", "Realized P&L"], table_key="transactions")
        layout.addWidget(self.transactions_table, 1)
        return page

    def _trade_clicked(self, side):
        symbol = self.trade_symbol_input.text().strip()
        shares = self.trade_shares_input.value()
        if not symbol:
            self.portfolio_status_label.setText("Enter a ticker symbol.")
            return
        self.portfolio_status_label.setText(f"Looking up {symbol.upper()}...")

        def work():
            return webagent._fetch_stock_quote(symbol.upper())

        def handle(quote):
            if quote is None:
                self.portfolio_status_label.setText(f'Could not get a live quote for "{symbol}".')
                return
            price = quote["price"]
            verb = "Buy" if side == "buy" else "Sell"
            reply = QMessageBox.question(
                self, f"{verb} {quote['symbol']}",
                f"{verb} {shares:g} share(s) of {quote['symbol']} at ${price:,.2f} "
                f"(total ${shares * price:,.2f})?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            try:
                if side == "buy":
                    buy_stock(quote["symbol"], shares, price)
                else:
                    sell_stock(quote["symbol"], shares, price)
            except ValueError as exc:
                self.portfolio_status_label.setText(str(exc))
                return
            self.trade_symbol_input.clear()
            self.portfolio_status_label.setText(f"{verb} order executed.")
            self._refresh_portfolio()

        worker = _FetchWorker(work)
        worker.result_ready.connect(handle)
        self._trade_worker = worker
        worker.start()

    def _reset_portfolio_clicked(self):
        reply = QMessageBox.question(
            self, "Reset Simulation",
            "Wipe all holdings and transaction history and reset cash? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        current_starting_cash = load_data()["portfolio"]["starting_cash"]
        new_cash, ok = QInputDialog.getDouble(
            self, "Starting Cash", "New starting cash balance:", current_starting_cash, 0, 100_000_000, 2,
        )
        if not ok:
            return
        reset_portfolio(starting_cash=new_cash)
        self.portfolio_status_label.setText("Simulation reset.")
        self._refresh_portfolio()

    def _refresh_portfolio(self):
        holdings = load_data()["portfolio"]["holdings"]
        symbols = [h["symbol"] for h in holdings]
        if not symbols:
            self._render_portfolio(portfolio_summary({}))
            return

        def work():
            return portfolio_summary(quotes_to_prices(fetch_quotes(symbols)))

        def handle(summary):
            self._render_portfolio(summary)

        worker = _FetchWorker(work)
        worker.result_ready.connect(handle)
        self._portfolio_worker = worker
        worker.start()

    def _render_portfolio(self, summary):
        self.cash_label.setText(f"Cash: {_money(summary['cash'])}")
        self.equity_label.setText(f"Total Equity: {_money(summary['total_equity'])}")
        self.unrealized_label.setText(f"Unrealized P&L: {_money(summary['total_unrealized_pnl'])}")
        self.realized_label.setText(f"Realized P&L: {_money(summary['total_realized_pnl'])}")

        holdings = summary["holdings"]
        self.holdings_table.setRowCount(len(holdings))
        for row, holding in enumerate(holdings):
            values = [
                holding["symbol"], f"{holding['shares']:g}", _money(holding["avg_cost"]),
                _money(holding["price"]), _money(holding["market_value"]), _money(holding["unrealized_pnl"]),
            ]
            for col, value in enumerate(values):
                self.holdings_table.setItem(row, col, QTableWidgetItem(str(value)))

        transactions = list(reversed(list_transactions()))
        self.transactions_table.setRowCount(len(transactions))
        for row, txn in enumerate(transactions):
            stamp = datetime.fromisoformat(txn["at"]).strftime("%Y-%m-%d %H:%M")
            values = [
                stamp, txn["symbol"], txn["side"].capitalize(), f"{txn['shares']:g}",
                _money(txn["price"]), _money(txn["amount"]), _money(txn["realized_pnl"]),
            ]
            for col, value in enumerate(values):
                self.transactions_table.setItem(row, col, QTableWidgetItem(str(value)))

    # ------------------------------------------------------------------
    # Congress - Senate Periodic Transaction Report disclosures. House is
    # deliberately out of scope (PDF-heavy, see stocks_congress.py).
    # ------------------------------------------------------------------
    def _build_congress_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        top_row = QHBoxLayout()
        refresh_button = QPushButton("↻ Refresh Filings")
        refresh_button.clicked.connect(self._refresh_congress_clicked)
        top_row.addWidget(refresh_button)
        self.congress_filter_input = QLineEdit()
        self.congress_filter_input.setPlaceholderText("Filter by senator name")
        self.congress_filter_input.textChanged.connect(self._apply_congress_filter)
        top_row.addWidget(self.congress_filter_input, 1)
        layout.addLayout(top_row)

        self.congress_status_label = QLabel(
            "Senate financial disclosures only (efdsearch.senate.gov) - House disclosures aren't parsed here."
        )
        self.congress_status_label.setWordWrap(True)
        layout.addWidget(self.congress_status_label)

        self.congress_table = QTableWidget(0, 5)
        _configure_table(self.congress_table, ["Date", "Senator", "Office", "Type", ""], table_key="congress")
        layout.addWidget(self.congress_table, 1)
        return page

    def _refresh_congress_clicked(self):
        self.congress_status_label.setText("Signing in and fetching filings...")

        def work():
            session = stocks_congress.open_session()
            if session is None:
                return {"error": "Could not reach efdsearch.senate.gov - try again later."}
            cookies, csrf_token = session
            filings = stocks_congress.list_ptr_filings(cookies, csrf_token)
            if filings is None:
                return {"error": "Filing search failed."}
            return {"cookies": cookies, "csrf_token": csrf_token, "filings": filings}

        def handle(result):
            if "error" in result:
                self.congress_status_label.setText(result["error"])
                return
            self._congress_cookies = result["cookies"]
            self._congress_csrf_token = result["csrf_token"]
            self._congress_filings = result["filings"]
            self.congress_status_label.setText(f"{len(result['filings'])} recent Periodic Transaction Report filing(s).")
            self._apply_congress_filter()

        worker = _FetchWorker(work)
        worker.result_ready.connect(handle)
        self._congress_worker = worker
        worker.start()

    def _apply_congress_filter(self):
        needle = self.congress_filter_input.text().strip().lower()
        filings = self._congress_filings
        if needle:
            filings = [f for f in filings if needle in f"{f['first_name']} {f['last_name']}".lower()]
        self.congress_table.setRowCount(len(filings))
        for row, filing in enumerate(filings):
            senator = f"{filing['first_name']} {filing['last_name']}"
            values = [filing["date_received"], senator, filing["office"], filing["kind"].upper()]
            for col, value in enumerate(values):
                self.congress_table.setItem(row, col, QTableWidgetItem(str(value)))
            if filing["kind"] == "ptr":
                details_button = QPushButton("Details")
                details_button.clicked.connect(lambda _checked=False, f=filing: self._view_congress_details_clicked(f))
            else:
                details_button = QPushButton("🔗 Open (PDF)")
                details_button.clicked.connect(lambda _checked=False, f=filing: QDesktopServices.openUrl(QUrl(f["detail_url"])))
            self.congress_table.setCellWidget(row, 4, details_button)

    def _view_congress_details_clicked(self, filing):
        dialog = QDialog(self)
        senator = f"{filing['first_name']} {filing['last_name']}"
        dialog.setWindowTitle(f"PTR — {senator} ({filing['date_received']})")
        dialog.resize(560, 400)
        layout = QVBoxLayout(dialog)
        status_label = QLabel("Loading transactions...")
        layout.addWidget(status_label)
        table = QTableWidget(0, 6)
        _configure_table(table, ["Date", "Ticker", "Asset", "Type", "Amount Range", "Owner"])
        layout.addWidget(table, 1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)

        def work():
            return stocks_congress.fetch_ptr_transactions(self._congress_cookies, self._congress_csrf_token, filing["detail_url"])

        def handle(transactions):
            if transactions is None:
                status_label.setText("Could not load this filing's transactions - PDF filing, or temporarily unavailable.")
                return
            status_label.setText(f"{len(transactions)} transaction(s).")
            table.setRowCount(len(transactions))
            for row, txn in enumerate(transactions):
                values = [
                    txn["transaction_date"], txn["ticker"], txn["asset_name"],
                    txn["transaction_type"], txn["amount_range"], txn["owner"],
                ]
                for col, value in enumerate(values):
                    table.setItem(row, col, QTableWidgetItem(str(value)))

        worker = _FetchWorker(work)
        worker.result_ready.connect(handle)
        dialog._detail_worker = worker  # keep a reference alive for the dialog's lifetime
        worker.start()
        dialog.exec()

    # ------------------------------------------------------------------
    # Notable Investors - 13F institutional holdings (SEC EDGAR)
    # ------------------------------------------------------------------
    def _build_investors_tab(self):
        page = QWidget()
        layout = QHBoxLayout(page)

        left = QVBoxLayout()
        left.addWidget(QLabel("Notable Investors"))
        self.investors_list = QListWidget()
        for investor in stocks_13f.NOTABLE_INVESTORS:
            item = QListWidgetItem(f"{investor['name']} — {investor['fund']}")
            item.setData(Qt.ItemDataRole.UserRole, investor)
            self.investors_list.addItem(item)
        self.investors_list.currentItemChanged.connect(self._investor_selected)
        left.addWidget(self.investors_list, 1)
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setFixedWidth(260)
        layout.addWidget(left_widget)

        right = QVBoxLayout()
        top_row = QHBoxLayout()
        self.investor_status_label = QLabel("Select an investor to view their latest 13F holdings.")
        self.investor_status_label.setWordWrap(True)
        top_row.addWidget(self.investor_status_label, 1)
        refresh_button = QPushButton("↻ Refresh")
        refresh_button.clicked.connect(self._refresh_selected_investor)
        top_row.addWidget(refresh_button)
        right.addLayout(top_row)
        self.investor_holdings_table = QTableWidget(0, 5)
        _configure_table(self.investor_holdings_table, ["Rank", "Company", "% of Portfolio", "Value", "Shares"], table_key="investor_holdings")
        right.addWidget(self.investor_holdings_table, 1)
        layout.addLayout(right, 1)
        return page

    def _investor_selected(self, current, _previous):
        if current is None:
            return
        investor = current.data(Qt.ItemDataRole.UserRole)
        if investor["cik"] in self._investor_cache:
            self._render_investor(investor, self._investor_cache[investor["cik"]])
            return
        self._fetch_investor(investor)

    def _refresh_selected_investor(self):
        item = self.investors_list.currentItem()
        if item is None:
            return
        investor = item.data(Qt.ItemDataRole.UserRole)
        self._investor_cache.pop(investor["cik"], None)
        self._fetch_investor(investor)

    def _fetch_investor(self, investor):
        self.investor_status_label.setText(f"Loading {investor['name']}'s latest 13F filing...")
        self.investor_holdings_table.setRowCount(0)

        def work():
            return stocks_13f.fetch_holdings_for_investor(investor["cik"])

        def handle(result):
            if result is None:
                self.investor_status_label.setText(f"Could not load a 13F filing for {investor['name']}.")
                return
            self._investor_cache[investor["cik"]] = result
            self._render_investor(investor, result)

        worker = _FetchWorker(work)
        worker.result_ready.connect(handle)
        self._investor_worker = worker
        worker.start()

    def _render_investor(self, investor, result):
        self.investor_status_label.setText(
            f"{investor['name']} ({investor['fund']}) — as of {result['report_date']} (filed {result['filing_date']})"
        )
        holdings = result["holdings"]
        self.investor_holdings_table.setRowCount(len(holdings))
        for row, holding in enumerate(holdings):
            values = [str(row + 1), holding["name"], f"{holding['pct_of_portfolio']:.2f}%", _money(holding["value"]), f"{holding['shares']:g}"]
            for col, value in enumerate(values):
                self.investor_holdings_table.setItem(row, col, QTableWidgetItem(str(value)))

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def _build_settings_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        settings = get_alert_settings()

        threshold_row = QHBoxLayout()
        threshold_row.addWidget(QLabel("Big-mover alert threshold:"))
        self.threshold_input = QDoubleSpinBox()
        self.threshold_input.setRange(0.1, 100.0)
        self.threshold_input.setSuffix(" %")
        self.threshold_input.setValue(settings["threshold_pct"])
        threshold_row.addWidget(self.threshold_input)
        threshold_row.addStretch()
        layout.addLayout(threshold_row)

        refresh_row = QHBoxLayout()
        refresh_row.addWidget(QLabel("Auto-refresh every:"))
        self.auto_refresh_input = QSpinBox()
        self.auto_refresh_input.setRange(1, 120)
        self.auto_refresh_input.setSuffix(" minute(s)")
        self.auto_refresh_input.setValue(int(settings["auto_refresh_minutes"]))
        refresh_row.addWidget(self.auto_refresh_input)
        refresh_row.addStretch()
        layout.addLayout(refresh_row)

        self.sound_checkbox = QCheckBox("Play a sound on a big-mover alert")
        self.sound_checkbox.setChecked(settings["sound_enabled"])
        layout.addWidget(self.sound_checkbox)

        cash_row = QHBoxLayout()
        cash_row.addWidget(QLabel("Starting cash for future resets:"))
        self.starting_cash_input = QDoubleSpinBox()
        self.starting_cash_input.setRange(0, 100_000_000)
        self.starting_cash_input.setDecimals(2)
        self.starting_cash_input.setValue(load_data()["portfolio"]["starting_cash"])
        cash_row.addWidget(self.starting_cash_input)
        cash_row.addStretch()
        layout.addLayout(cash_row)

        save_button = QPushButton("Save Settings")
        save_button.clicked.connect(self._save_settings_clicked)
        layout.addWidget(save_button)

        self.settings_status_label = QLabel("")
        layout.addWidget(self.settings_status_label)

        scope_note = QLabel(
            "Scope notes: Congress tab covers Senate disclosures only (no House - those are mostly PDF scans). "
            "13F institutional holdings are quarterly and reported with a real ~45-day filing lag, never live. "
            "Paper (non-electronic) Senate filings aren't parsed - only linked."
        )
        scope_note.setWordWrap(True)
        scope_note.setStyleSheet("color: gray;")
        layout.addWidget(scope_note)
        layout.addStretch()
        return page

    def _save_settings_clicked(self):
        set_alert_settings(
            threshold_pct=self.threshold_input.value(),
            sound_enabled=self.sound_checkbox.isChecked(),
            auto_refresh_minutes=self.auto_refresh_input.value(),
        )
        data = load_data()
        data["portfolio"]["starting_cash"] = self.starting_cash_input.value()
        save_data(data)
        self._apply_refresh_interval()
        self.settings_status_label.setText("Settings saved.")
