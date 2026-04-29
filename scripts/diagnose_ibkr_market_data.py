from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from broker.contracts import OptionChainRequest
from broker.ibkr_client import IbkrClient


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify live IBKR stock and option market data through TWS/Gateway."
    )
    parser.add_argument("symbol", nargs="?", default="AAPL")
    parser.add_argument("--max-strikes", type=int, default=5)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    client = IbkrClient()
    try:
        client.connect()
        quotes = client.fetch_underlying_quotes([args.symbol])
        if not quotes:
            print(f"No underlying quote returned for {args.symbol}.")
            return 2

        quote = quotes[0]
        print("\nUnderlying")
        print(f"  symbol={quote.symbol}")
        print(f"  bid={quote.bid} ask={quote.ask} last={quote.last_price}")
        print(f"  volume={quote.volume}")
        print(f"  market_data_type={quote.market_data_type}")
        print(f"  warnings={quote.data_quality_warnings}")

        options = client.fetch_option_chain(
            OptionChainRequest(underlying_symbol=args.symbol)
        )
        print("\nOptions")
        for option in options[: args.max_strikes]:
            print(
                "  "
                f"{option.symbol} bid={option.bid} ask={option.ask} "
                f"delta={option.delta} iv={option.implied_volatility} "
                f"oi={option.open_interest} volume={option.volume} "
                f"market_data_type={option.market_data_type} "
                f"warnings={option.data_quality_warnings}"
            )

        if not options:
            print("No option contracts returned. Check option permissions and chain filters.")
            return 3

        non_live = [
            option
            for option in options
            if option.market_data_type != "live" or option.data_quality_warnings
        ]
        if quote.market_data_type != "live" or quote.data_quality_warnings or non_live:
            print(
                "\nData quality warning: at least one quote was not confirmed live "
                "or has missing fields."
            )
            return 4

        print("\nLive stock and option data verified.")
        return 0
    finally:
        client.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
