"""Binance demo trading from the terminal (D048): make a key, test it, see the account, or flatten.

  keygen    Make a self-generated Ed25519 key. The private key stays on this computer, and
            the public key is printed for Binance's "Self-generated" API key form.
  check     Binance's clock, the account's balances and its position mode.
  status    Positions, the stops and targets Binance holds, and the latest stored orders.
  flatten   The kill switch: cancel every stop and target, then close every position.

Test funds only. The host is fixed to https://demo-fapi.binance.com. Keys are read from .env
and never printed.
"""

import argparse
import asyncio
import time
from decimal import Decimal
from pathlib import Path

from trading_intel.core.settings import load_settings
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.exchange import ExchangeRepository
from trading_intel.database.repositories.signals import (
    EXCHANGE_DEMO_ACCOUNT,
    EXCHANGE_DEMO_BUDGET,
    EXCHANGE_DEMO_MODE,
    SignalRepository,
)
from trading_intel.execution.binance_futures import (
    DEMO_REST_URL,
    BinanceFuturesGateway,
    generate_key_file,
    signer_for,
)
from trading_intel.execution.trader import Budget, FuturesTrader
from trading_intel.trade_signals.portfolio import PLAN_PROFILE


def _usdt(value: Decimal) -> str:
    return f"{value:,.2f} USDT"


async def check(gateway: BinanceFuturesGateway) -> None:
    offset = await gateway.sync_clock()
    account = await gateway.account()
    one_way = await gateway.one_way_mode()
    print(f"Host: {DEMO_REST_URL} (test funds)")
    direction = "behind" if offset >= 0 else "ahead of"
    print(f"Clock: this Mac is {abs(offset)} ms {direction} Binance")
    print(f"Wallet: {_usdt(Decimal(account['totalWalletBalance']))}")
    print(f"Equity: {_usdt(Decimal(account['totalMarginBalance']))}")
    print(f"Available for margin: {_usdt(Decimal(account['availableBalance']))}")
    print(f"Position mode: {'one-way' if one_way else 'hedge (the bot switches it to one-way)'}")
    print("The keys can read this account. Trading permission is proven by the first order.")


async def status(trader: FuturesTrader, gateway: BinanceFuturesGateway) -> None:
    view = await trader.view()
    print(f"Equity {_usdt(view.equity)}, available {_usdt(view.available)}")
    if not view.positions:
        print("No open positions.")
    for symbol, position in sorted(view.positions.items()):
        print(
            f"{symbol}: {position.side.value} {abs(position.amount)} at {position.entry_price}, "
            f"worth {_usdt(position.notional)}"
        )
    for order in await gateway.open_algo_orders():
        print(
            f"  {order['symbol']} {order.get('orderType', order.get('type'))} {order['side']} "
            f"at {order.get('triggerPrice')}"
            f"{' for the whole position' if order.get('closePosition') else ''}"
            f"{'' if order.get('closePosition') else ' quantity ' + str(order.get('quantity'))}"
        )


def keygen(path: Path) -> None:
    public = generate_key_file(path)
    print(f"Private key saved to {path}, readable only by you. Never share or move it.")
    print("Paste this public key into demo.binance.com > Demo Trading API > Create API >")
    print("Self-generated, then copy the API key Binance shows into .env as BINANCE_DEMO_API_KEY:")
    print()
    print(public)


async def run(command: str, confirmed: bool) -> None:
    settings = load_settings()
    key = settings.binance_demo_api_key.get_secret_value()
    secret = settings.binance_demo_api_secret.get_secret_value()
    signer = signer_for(secret, settings.binance_demo_private_key_file)
    gateway = BinanceFuturesGateway(key, signer)
    trader = FuturesTrader(gateway)
    engine = create_engine(settings.database_url)
    orders = ExchangeRepository(engine)
    try:
        account = await SignalRepository(engine).ensure_account(
            settings.owner_email,
            EXCHANGE_DEMO_ACCOUNT,
            EXCHANGE_DEMO_BUDGET,
            PLAN_PROFILE,
            mode=EXCHANGE_DEMO_MODE,
        )
        if command == "check":
            await check(gateway)
        elif command == "status":
            await status(trader, gateway)
            if account is not None:
                view = await trader.view()
                baseline = await orders.baseline(account.id) or view.equity
                budget = Budget.of(view, account.starting_balance, baseline, baseline)
                print(
                    f"The bot trades {_usdt(account.starting_balance)} of it: equity "
                    f"{_usdt(budget.equity)} after its own profit and loss, "
                    f"{_usdt(budget.available)} free for margin."
                )
                print("Latest orders stored:")
                for row in await orders.recent(account.id, 10):
                    outcome = "answered" if row["answered"] else f"failed: {row['error']}"
                    when = f"{row['created_at']:%Y-%m-%d %H:%M:%S}"
                    print(f"  {when} {row['symbol']} {row['kind']}, {outcome}")
        elif command == "flatten":
            if not confirmed:
                print("This cancels every stop and target and closes every demo position.")
                print("Run again with --yes to do it.")
                return
            for record in await trader.flatten_all():
                if account is not None:
                    await orders.record(account.id, None, record)
                outcome = "done" if record.response is not None else f"failed: {record.error}"
                print(f"{record.symbol} {record.kind}: {outcome}")
            await status(trader, gateway)
    finally:
        await gateway.aclose()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=("keygen", "check", "status", "flatten"))
    parser.add_argument("--yes", action="store_true", help="confirm flatten")
    arguments = parser.parse_args()
    if arguments.command == "keygen":
        keygen(load_settings().binance_demo_private_key_file)
        return
    started = time.monotonic()
    asyncio.run(run(arguments.command, arguments.yes))
    print(f"Done in {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    main()
