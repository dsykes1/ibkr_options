from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from broker.base import Broker
from broker.contracts import BrokerConnection, OptionChainRequest, expiry_datetime, same_week_friday
from data.models import OptionQuote, UnderlyingQuote


LOGGER = logging.getLogger(__name__)

IBKR_MARKET_DATA_TYPES = {
    1: "live",
    2: "frozen",
    3: "delayed",
    4: "delayed_frozen",
}
IBKR_MARKET_DATA_TYPE_CODES = {value: key for key, value in IBKR_MARKET_DATA_TYPES.items()}

TICK_BID = 1
TICK_ASK = 2
TICK_LAST = 4
TICK_VOLUME = 8
TICK_MODEL_OPTION_COMPUTATION = 13
TICK_PUT_OPEN_INTEREST = 28
TICK_PUT_VOLUME = 30
TICK_DELAYED_BID = 66
TICK_DELAYED_ASK = 67
TICK_DELAYED_LAST = 68
TICK_DELAYED_VOLUME = 74
TICK_DELAYED_MODEL_OPTION_COMPUTATION = 83

GENERIC_TICKS_OPTION_VOLUME_OPEN_INTEREST = "100,101"


@dataclass
class IbkrClientConfig:
    host: str
    port: int
    client_id: int
    connect_timeout: float = 10
    market_data_timeout: float = 6
    max_option_contracts: int = 30
    chain_strike_window_pct: float = 0.15
    market_data_type: str = "live"

    @classmethod
    def from_env(cls) -> IbkrClientConfig:
        return cls(
            host=os.getenv("IBKR_HOST", "127.0.0.1"),
            port=int(os.getenv("IBKR_PORT", "7497")),
            client_id=int(os.getenv("IBKR_CLIENT_ID", "1")),
            connect_timeout=float(os.getenv("IBKR_CONNECT_TIMEOUT", "10")),
            market_data_timeout=float(os.getenv("IBKR_MARKET_DATA_TIMEOUT", "6")),
            max_option_contracts=int(os.getenv("IBKR_MAX_OPTION_CONTRACTS", "30")),
            chain_strike_window_pct=float(
                os.getenv("IBKR_CHAIN_STRIKE_WINDOW_PCT", "0.15")
            ),
            market_data_type=os.getenv("IBKR_MARKET_DATA_TYPE", "live"),
        )


@dataclass
class IbkrMarketDataSnapshot:
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    volume: int | None = None
    option_volume: int | None = None
    open_interest: int | None = None
    implied_volatility: Decimal | None = None
    delta: Decimal | None = None
    market_data_type: str | None = None
    unavailable_fields: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _OptionDefinition:
    symbol: str
    exchange: str
    trading_class: str
    multiplier: str
    expiration: str
    strike: Decimal
    right: str


class IbkrClient(Broker):
    """IBKR TWS/Gateway broker adapter.

    This class preserves the project broker interface and keeps raw IBKR callback
    normalization inside the broker layer. It does not place orders.
    """

    def __init__(
        self,
        config: IbkrClientConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config or IbkrClientConfig.from_env()
        self.logger = logger or LOGGER
        self._connection = BrokerConnection(
            host=self.config.host,
            port=self.config.port,
            client_id=self.config.client_id,
            connected=False,
        )
        self._app: _IbkrApp | None = None
        self._thread: threading.Thread | None = None

    def connect(self) -> None:
        EClient, EWrapper, _Contract = _load_ibapi()
        app = _IbkrApp(EWrapper=EWrapper, EClient=EClient, logger=self.logger)
        app.connect(self.config.host, self.config.port, self.config.client_id)
        thread = threading.Thread(target=app.run, daemon=True)
        thread.start()

        if not app.connected_event.wait(self.config.connect_timeout):
            app.disconnect()
            raise TimeoutError("Timed out waiting for IBKR nextValidId callback.")

        market_data_type_code = IBKR_MARKET_DATA_TYPE_CODES.get(
            self.config.market_data_type,
            1,
        )
        app.reqMarketDataType(market_data_type_code)
        self.logger.info(
            "Requested IBKR %s market data with reqMarketDataType(%s).",
            IBKR_MARKET_DATA_TYPES.get(market_data_type_code, "live"),
            market_data_type_code,
        )

        self._app = app
        self._thread = thread
        self._connection = BrokerConnection(
            host=self.config.host,
            port=self.config.port,
            client_id=self.config.client_id,
            connected=True,
        )

    def disconnect(self) -> None:
        if self._app is not None:
            self._app.disconnect()
        self._connection = BrokerConnection(
            host=self.config.host,
            port=self.config.port,
            client_id=self.config.client_id,
            connected=False,
        )

    @property
    def is_connected(self) -> bool:
        return self._connection.connected and self._app is not None

    def fetch_underlying_quotes(self, symbols: list[str]) -> list[UnderlyingQuote]:
        self._ensure_connected()
        quotes: list[UnderlyingQuote] = []
        for symbol in symbols:
            contract = _stock_contract(symbol)
            snapshot = self._request_market_data(
                contract=contract,
                generic_ticks="",
                description=f"underlying {symbol.upper()}",
                essential_fields=["bid", "ask", "last"],
            )
            if snapshot.last is None and snapshot.bid is None and snapshot.ask is None:
                self.logger.warning(
                    "IBKR underlying %s missing essential quote fields: %s",
                    symbol.upper(),
                    snapshot.unavailable_fields,
                )
                continue

            quote = UnderlyingQuote(
                symbol=symbol.upper(),
                last_price=snapshot.last or _midpoint(snapshot.bid, snapshot.ask),
                bid=snapshot.bid,
                ask=snapshot.ask,
                volume=snapshot.volume,
                market_timestamp=datetime.now(),
                market_data_type=snapshot.market_data_type,
                data_quality_warnings=_data_quality_warnings(snapshot),
            )
            self._log_data_quality(f"underlying {symbol.upper()}", snapshot)
            quotes.append(quote)

        return quotes

    def fetch_option_chain(self, request: OptionChainRequest) -> list[OptionQuote]:
        self._ensure_connected()
        underlying = self._qualify_underlying(request.underlying_symbol)
        underlying_quote = self.fetch_underlying_quotes([request.underlying_symbol])
        spot = underlying_quote[0].last_price if underlying_quote else None
        definitions = self._option_definitions(request, underlying, spot)
        option_quotes: list[OptionQuote] = []

        for definition in definitions:
            contract = _option_contract(definition)
            snapshot = self._request_market_data(
                contract=contract,
                generic_ticks=GENERIC_TICKS_OPTION_VOLUME_OPEN_INTEREST,
                description=f"option {definition.symbol}",
                essential_fields=[
                    "bid",
                    "ask",
                    "implied_volatility",
                    "delta",
                    "open_interest",
                    "option_volume",
                ],
            )
            quote = self._normalize_option_quote(definition, snapshot)
            if quote is not None:
                option_quotes.append(quote)

        return option_quotes

    def fetch_option_bid_ask(self, option_contract: Any) -> tuple[Decimal | None, Decimal | None]:
        snapshot = self._request_market_data(
            contract=option_contract,
            generic_ticks="",
            description="option bid/ask",
            essential_fields=["bid", "ask"],
        )
        return snapshot.bid, snapshot.ask

    def fetch_iv(self, option_contract: Any) -> Decimal | None:
        snapshot = self._request_market_data(
            contract=option_contract,
            generic_ticks="",
            description="option IV",
            essential_fields=["implied_volatility"],
        )
        return snapshot.implied_volatility

    def fetch_delta(self, option_contract: Any) -> Decimal | None:
        snapshot = self._request_market_data(
            contract=option_contract,
            generic_ticks="",
            description="option delta",
            essential_fields=["delta"],
        )
        return snapshot.delta

    def fetch_open_interest(self, option_contract: Any) -> int | None:
        snapshot = self._request_market_data(
            contract=option_contract,
            generic_ticks="101",
            description="option open interest",
            essential_fields=["open_interest"],
        )
        return snapshot.open_interest

    def fetch_option_volume(self, option_contract: Any) -> int | None:
        snapshot = self._request_market_data(
            contract=option_contract,
            generic_ticks="100",
            description="option volume",
            essential_fields=["option_volume"],
        )
        return snapshot.option_volume

    def filter_same_week_friday_expiry(
        self,
        options: list[OptionQuote],
        as_of: date | None = None,
    ) -> list[OptionQuote]:
        target_expiry = same_week_friday(as_of)
        return [
            option
            for option in options
            if option.expiration_date.date() == target_expiry
        ]

    def _qualify_underlying(self, symbol: str) -> Any:
        contract = _stock_contract(symbol)
        req_id = self._app.next_req_id()
        event = self._app.register_contract_details_request(req_id)
        self._app.reqContractDetails(req_id, contract)
        if not event.wait(self.config.connect_timeout):
            raise TimeoutError(f"Timed out qualifying underlying {symbol.upper()}.")

        details = self._app.contract_details.pop(req_id, [])
        if not details:
            raise RuntimeError(f"IBKR returned no contract details for {symbol.upper()}.")

        return details[0].contract

    def _option_definitions(
        self,
        request: OptionChainRequest,
        underlying_contract: Any,
        spot: Decimal | None,
    ) -> list[_OptionDefinition]:
        req_id = self._app.next_req_id()
        event = self._app.register_option_params_request(req_id)
        self._app.reqSecDefOptParams(
            req_id,
            request.underlying_symbol.upper(),
            "",
            "STK",
            underlying_contract.conId,
        )
        if not event.wait(self.config.connect_timeout):
            raise TimeoutError(
                f"Timed out fetching option parameters for {request.underlying_symbol}."
            )

        params = self._app.option_params.pop(req_id, [])
        target_expiry = same_week_friday(request.as_of).strftime("%Y%m%d")
        right = "P" if request.option_right == "put" else "C"
        definitions: list[_OptionDefinition] = []

        for param in params:
            expirations = set(param["expirations"])
            if target_expiry not in expirations:
                continue

            strikes = sorted(Decimal(str(strike)) for strike in param["strikes"])
            for strike in strikes:
                if request.min_strike is not None and strike < request.min_strike:
                    continue
                if request.max_strike is not None and strike > request.max_strike:
                    continue
                if not _strike_near_spot(
                    strike,
                    spot,
                    self.config.chain_strike_window_pct,
                ):
                    continue

                definitions.append(
                    _OptionDefinition(
                        symbol=request.underlying_symbol.upper(),
                        exchange=param["exchange"] or "SMART",
                        trading_class=param["trading_class"],
                        multiplier=param["multiplier"] or "100",
                        expiration=target_expiry,
                        strike=strike,
                        right=right,
                    )
                )

        limited = definitions[: self.config.max_option_contracts]
        self.logger.info(
            "IBKR option chain %s: selected %s/%s contracts for expiry %s.",
            request.underlying_symbol.upper(),
            len(limited),
            len(definitions),
            target_expiry,
        )
        return limited

    def _request_market_data(
        self,
        *,
        contract: Any,
        generic_ticks: str,
        description: str,
        essential_fields: list[str],
    ) -> IbkrMarketDataSnapshot:
        req_id = self._app.next_req_id()
        self._app.market_data[req_id] = IbkrMarketDataSnapshot()
        self._app.reqMktData(req_id, contract, generic_ticks, False, False, [])
        self.logger.info(
            "IBKR reqMktData %s reqId=%s genericTicks=%s.",
            description,
            req_id,
            generic_ticks or "<none>",
        )

        deadline = time.monotonic() + self.config.market_data_timeout
        while time.monotonic() < deadline:
            snapshot = self._app.market_data[req_id]
            if _has_any(snapshot, essential_fields):
                time.sleep(0.25)
                break
            time.sleep(0.05)

        self._app.cancelMktData(req_id)
        snapshot = self._app.market_data.pop(req_id, IbkrMarketDataSnapshot())
        snapshot.unavailable_fields = [
            field for field in essential_fields if getattr(snapshot, field) is None
        ]
        self._log_data_quality(description, snapshot)
        return snapshot

    def _normalize_option_quote(
        self,
        definition: _OptionDefinition,
        snapshot: IbkrMarketDataSnapshot,
    ) -> OptionQuote | None:
        if snapshot.bid is None or snapshot.ask is None:
            self.logger.warning(
                "Rejecting %s %s %s%s: missing essential bid/ask fields: %s.",
                definition.symbol,
                definition.expiration,
                definition.strike,
                definition.right,
                snapshot.unavailable_fields,
            )
            return None

        data_quality_warnings = _data_quality_warnings(snapshot)
        if snapshot.unavailable_fields:
            data_quality_warnings.append(
                "missing_fields:" + ",".join(snapshot.unavailable_fields)
            )

        return OptionQuote(
            symbol=(
                f"{definition.symbol} {definition.expiration} "
                f"{definition.strike}{definition.right}"
            ),
            underlying_symbol=definition.symbol,
            expiration_date=expiry_datetime(
                datetime.strptime(definition.expiration, "%Y%m%d").date()
            ),
            strike=definition.strike,
            option_type="put" if definition.right == "P" else "call",
            bid=snapshot.bid,
            ask=snapshot.ask,
            last_price=snapshot.last,
            volume=snapshot.option_volume or snapshot.volume,
            open_interest=snapshot.open_interest,
            implied_volatility=snapshot.implied_volatility,
            delta=snapshot.delta,
            market_timestamp=datetime.now(),
            market_data_type=snapshot.market_data_type,
            data_quality_warnings=data_quality_warnings,
        )

    def _log_data_quality(self, description: str, snapshot: IbkrMarketDataSnapshot) -> None:
        data_type = snapshot.market_data_type or "unknown"
        if data_type != "live":
            self.logger.warning(
                "IBKR %s returned market data type %s; final recommendations must flag it.",
                description,
                data_type,
            )
        if snapshot.unavailable_fields:
            self.logger.warning(
                "IBKR %s unavailable fields: %s.",
                description,
                ", ".join(snapshot.unavailable_fields),
            )
        self.logger.info(
            "IBKR %s fields: bid=%s ask=%s last=%s iv=%s delta=%s oi=%s opt_volume=%s data_type=%s.",
            description,
            snapshot.bid,
            snapshot.ask,
            snapshot.last,
            snapshot.implied_volatility,
            snapshot.delta,
            snapshot.open_interest,
            snapshot.option_volume,
            data_type,
        )

    def _ensure_connected(self) -> None:
        if not self.is_connected or self._app is None:
            raise RuntimeError("IbkrClient is not connected.")


class _IbkrApp:
    def __init__(self, *, EWrapper: type, EClient: type, logger: logging.Logger) -> None:
        class App(EWrapper, EClient):  # type: ignore[misc, valid-type]
            pass

        self.__class__ = type("_RuntimeIbkrApp", (App, _IbkrApp), {})
        EWrapper.__init__(self)
        EClient.__init__(self, wrapper=self)
        self.logger = logger
        self.connected_event = threading.Event()
        self._req_id = 1
        self._lock = threading.Lock()
        self.contract_detail_events: dict[int, threading.Event] = {}
        self.contract_details: dict[int, list[Any]] = {}
        self.option_param_events: dict[int, threading.Event] = {}
        self.option_params: dict[int, list[dict[str, Any]]] = {}
        self.market_data: dict[int, IbkrMarketDataSnapshot] = {}

    def next_req_id(self) -> int:
        with self._lock:
            req_id = self._req_id
            self._req_id += 1
            return req_id

    def register_contract_details_request(self, req_id: int) -> threading.Event:
        event = threading.Event()
        self.contract_detail_events[req_id] = event
        self.contract_details[req_id] = []
        return event

    def register_option_params_request(self, req_id: int) -> threading.Event:
        event = threading.Event()
        self.option_param_events[req_id] = event
        self.option_params[req_id] = []
        return event

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.connected_event.set()
        self.logger.info("IBKR connected; nextValidId=%s.", orderId)

    def error(self, reqId: int, errorCode: int, errorString: str, *args: Any) -> None:  # noqa: N802
        self.logger.warning("IBKR error reqId=%s code=%s: %s", reqId, errorCode, errorString)

    def contractDetails(self, reqId: int, contractDetails: Any) -> None:  # noqa: N802
        self.contract_details.setdefault(reqId, []).append(contractDetails)

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        event = self.contract_detail_events.get(reqId)
        if event:
            event.set()

    def securityDefinitionOptionParameter(  # noqa: N802
        self,
        reqId: int,
        exchange: str,
        underlyingConId: int,
        tradingClass: str,
        multiplier: str,
        expirations: set[str],
        strikes: set[float],
    ) -> None:
        self.option_params.setdefault(reqId, []).append(
            {
                "exchange": exchange,
                "underlying_con_id": underlyingConId,
                "trading_class": tradingClass,
                "multiplier": multiplier,
                "expirations": expirations,
                "strikes": strikes,
            }
        )

    def securityDefinitionOptionParameterEnd(self, reqId: int) -> None:  # noqa: N802
        event = self.option_param_events.get(reqId)
        if event:
            event.set()

    def marketDataType(self, reqId: int, marketDataType: int) -> None:  # noqa: N802
        snapshot = self.market_data.setdefault(reqId, IbkrMarketDataSnapshot())
        snapshot.market_data_type = IBKR_MARKET_DATA_TYPES.get(
            marketDataType,
            f"unknown_{marketDataType}",
        )

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib: Any) -> None:  # noqa: N802
        if price is None or price < 0:
            return
        snapshot = self.market_data.setdefault(reqId, IbkrMarketDataSnapshot())
        value = Decimal(str(price))
        if tickType in {TICK_BID, TICK_DELAYED_BID}:
            snapshot.bid = value
        elif tickType in {TICK_ASK, TICK_DELAYED_ASK}:
            snapshot.ask = value
        elif tickType in {TICK_LAST, TICK_DELAYED_LAST}:
            snapshot.last = value

    def tickSize(self, reqId: int, tickType: int, size: int) -> None:  # noqa: N802
        if size is None or size < 0:
            return
        snapshot = self.market_data.setdefault(reqId, IbkrMarketDataSnapshot())
        if tickType in {TICK_VOLUME, TICK_DELAYED_VOLUME}:
            snapshot.volume = int(size)
        elif tickType == TICK_PUT_OPEN_INTEREST:
            snapshot.open_interest = int(size)
        elif tickType == TICK_PUT_VOLUME:
            snapshot.option_volume = int(size)

    def tickOptionComputation(  # noqa: N802
        self,
        reqId: int,
        tickType: int,
        tickAttrib: int,
        impliedVol: float,
        delta: float,
        optPrice: float,
        pvDividend: float,
        gamma: float,
        vega: float,
        theta: float,
        undPrice: float,
    ) -> None:
        if tickType not in {
            TICK_MODEL_OPTION_COMPUTATION,
            TICK_DELAYED_MODEL_OPTION_COMPUTATION,
        }:
            return
        snapshot = self.market_data.setdefault(reqId, IbkrMarketDataSnapshot())
        if impliedVol is not None and impliedVol >= 0:
            snapshot.implied_volatility = Decimal(str(impliedVol))
        if delta is not None and -2 < delta < 2:
            snapshot.delta = Decimal(str(delta))


def _load_ibapi() -> tuple[type, type, type]:
    try:
        from ibapi.client import EClient
        from ibapi.contract import Contract
        from ibapi.wrapper import EWrapper
    except ImportError as exc:
        raise RuntimeError(
            "ibapi is required for IbkrClient. Install project dependencies with "
            "`.venv/bin/uv pip install -e .[dev]` or `uv pip install -e .[dev]`."
        ) from exc

    return EClient, EWrapper, Contract


def _stock_contract(symbol: str) -> Any:
    _EClient, _EWrapper, Contract = _load_ibapi()
    contract = Contract()
    contract.symbol = symbol.upper()
    contract.secType = "STK"
    contract.exchange = "SMART"
    contract.currency = "USD"
    return contract


def _option_contract(definition: _OptionDefinition) -> Any:
    _EClient, _EWrapper, Contract = _load_ibapi()
    contract = Contract()
    contract.symbol = definition.symbol
    contract.secType = "OPT"
    contract.exchange = "SMART"
    contract.currency = "USD"
    contract.lastTradeDateOrContractMonth = definition.expiration
    contract.strike = float(definition.strike)
    contract.right = definition.right
    contract.multiplier = definition.multiplier
    contract.tradingClass = definition.trading_class
    return contract


def _midpoint(bid: Decimal | None, ask: Decimal | None) -> Decimal:
    if bid is not None and ask is not None:
        return (bid + ask) / Decimal("2")
    if bid is not None:
        return bid
    if ask is not None:
        return ask
    raise ValueError("Cannot compute midpoint without bid or ask.")


def _has_any(snapshot: IbkrMarketDataSnapshot, fields: list[str]) -> bool:
    return any(getattr(snapshot, field) is not None for field in fields)


def _strike_near_spot(
    strike: Decimal,
    spot: Decimal | None,
    window_pct: float,
) -> bool:
    if spot is None:
        return True
    lower = spot * (Decimal("1") - Decimal(str(window_pct)))
    upper = spot * (Decimal("1") + Decimal(str(window_pct)))
    return lower <= strike <= upper


def _data_quality_warnings(snapshot: IbkrMarketDataSnapshot) -> list[str]:
    warnings: list[str] = []
    if snapshot.market_data_type and snapshot.market_data_type != "live":
        warnings.append(f"market_data_type:{snapshot.market_data_type}")
    elif snapshot.market_data_type is None:
        warnings.append("market_data_type:unknown")
    return warnings
