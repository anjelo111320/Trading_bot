"""The owner's real Binance futures account from the terminal (D060).

  keygen    Make a self-generated Ed25519 key for the real account. The private key stays on
            this computer, and the public key is printed for Binance's "Self-generated" form.
  check     What the key may do, the account's position and margin modes, and the futures
            wallet. Reads only.
  status    Positions and orders, the bot's and your own, and whether trading is armed.
  arm       Let the bot open trades on the real account, once the check passes. Needs --yes.
  disarm    Stop new trades. Open trades keep their stops and targets on Binance.
  flatten   Close the bot's trades at market and cancel its orders. Yours stay. Needs --yes.

Real money. The host is fixed to https://fapi.binance.com, the bot can call USDⓈ-M futures
endpoints only, and it refuses a key that can withdraw, transfer or trade anything else. Keys
are read from .env and never printed.
"""

import argparse
import asyncio
import time
from decimal import Decimal
from pathlib import Path

from trading_intel.core.errors import ConfigurationError
from trading_intel.core.settings import load_settings
from trading_intel.database.engine import create_engine
from trading_intel.database.repositories.exchange import ExchangeRepository
from trading_intel.database.repositories.signals import Account, SignalRepository
from trading_intel.execution.binance_futures import (
    LIVE_REST_URL,
    BinanceError,
    BinanceFuturesGateway,
    generate_key_file,
    signer_for,
)
from trading_intel.execution.key_check import AccountCheck, KeyChecker, check_account
from trading_intel.execution.trader import FuturesTrader, by_bot
from trading_intel.risk_management.models import RiskProfile
from trading_intel.trade_signals.exchange_accounts import LIVE


def _usdt(value: Decimal) -> str:
    return f"{value:,.2f} USDT"


def _percent(value: Decimal | None) -> str:
    return "off" if value is None else f"{value * 100:g}%"


def limits(profile: RiskProfile) -> list[str]:
    return [
        f"risk per trade {_percent(profile.max_risk_fraction)}",
        f"risk across open trades {_percent(profile.max_open_risk_fraction)}",
        f"daily loss limit {_percent(profile.max_daily_loss_fraction)}",
        f"positions within {_percent(profile.max_total_exposure_fraction)} of equity",
        f"leverage up to x{profile.max_leverage:g}",
        f"daily profit stop {_percent(profile.daily_profit_stop_fraction)}",
        f"loss stop {_percent(profile.max_total_loss_fraction)}",
    ]


async def check(gateway: BinanceFuturesGateway, keys: KeyChecker) -> AccountCheck:
    found = await check_account(gateway, keys)
    print(f"Host: {LIVE_REST_URL} (real money, USDⓈ-M futures only)")
    try:
        account = await gateway.account()
        print(f"Futures wallet: {_usdt(Decimal(account['totalWalletBalance']))}")
        print(f"Equity: {_usdt(Decimal(account['totalMarginBalance']))}")
        print(f"Available for margin: {_usdt(Decimal(account['availableBalance']))}")
    except BinanceError as error:
        print(f"The futures wallet could not be read: {error.message[:160]}")
    if found.ip_restricted:
        print("IP restriction: on")
    else:
        print("IP restriction: off. Binance recommends restricting the key to this IP.")
    for problem in found.problems:
        print(f"Problem: {problem}")
    if found.problems:
        print("Not ready: fix the problems above on Binance, then run check again.")
    else:
        print("The key can read and trade futures only. Ready to arm.")
    return found


async def status(
    trader: FuturesTrader,
    gateway: BinanceFuturesGateway,
    orders: ExchangeRepository,
    account: Account | None,
) -> None:
    view = await trader.view()
    trades = set(await orders.open_trades(account.id)) if account is not None else set()
    print(f"Equity {_usdt(view.equity)}, available {_usdt(view.available)}")
    if account is not None:
        armed, at, by = await orders.arming(account.id)
        when = f" since {at:%Y-%m-%d %H:%M} UTC by {by}" if at is not None else ""
        print(f"Trading: {'armed' if armed else 'not armed'}{when}")
    if not view.positions:
        print("No open positions.")
    for symbol, position in sorted(view.positions.items()):
        owner = "the bot's" if symbol in trades else "yours, the bot leaves it alone"
        print(
            f"{symbol}: {position.side.value} {abs(position.amount)} at {position.entry_price}, "
            f"worth {_usdt(position.notional)}, {owner}"
        )
    for order in await gateway.open_algo_orders():
        owner = "bot" if by_bot(order) else "yours"
        print(
            f"  {order['symbol']} {order.get('orderType', order.get('type'))} {order['side']} "
            f"at {order.get('triggerPrice')} ({owner})"
        )


def keygen(path: Path) -> None:
    public = generate_key_file(path)
    print(f"Private key saved to {path}, readable only by you. Never share or move it.")
    print("On binance.com: Account > API Management > Create API > Self-generated. Paste this")
    print("public key, then tick Enable Futures only (Enable Reading is always on). Leave")
    print("withdrawals, transfers, spot, margin and options off: the bot refuses such a key.")
    print("If your internet has a fixed IP, restrict the key to it. Copy the API key Binance")
    print("shows into .env as BINANCE_LIVE_API_KEY, then run: binance_live check")
    print()
    print(public)


async def ensure(accounts: SignalRepository, trader: FuturesTrader, email: str) -> Account | None:
    """The real account, made from the futures wallet's equity if the worker has not made it."""
    account = await accounts.find_account(email, LIVE.name)
    if account is not None:
        return account
    equity = (await trader.view()).equity
    if equity <= 0:
        return None
    return await accounts.ensure_account(email, LIVE.name, equity, LIVE.profile, mode=LIVE.mode)


async def run(command: str, confirmed: bool) -> None:
    settings = load_settings()
    key = settings.binance_live_api_key.get_secret_value()
    secret = settings.binance_live_api_secret.get_secret_value()
    if not key:
        print("BINANCE_LIVE_API_KEY is not set in .env. Run keygen, make the key on Binance,")
        print("then put the API key Binance shows in .env and run this again.")
        return
    try:
        signer = signer_for(secret, settings.binance_live_private_key_file)
    except ConfigurationError as error:
        print(f"{error.message}. Run keygen first, or set BINANCE_LIVE_API_SECRET for an HMAC key.")
        return
    gateway = BinanceFuturesGateway(key, signer, venue="live")
    keys = KeyChecker(key, signer, now_ms=gateway.server_ms)
    trader = FuturesTrader(gateway, own_only=True)
    engine = create_engine(settings.database_url)
    orders = ExchangeRepository(engine)
    accounts = SignalRepository(engine)
    email = settings.owner_email
    try:
        if command == "check":
            await check(gateway, keys)
        elif command == "status":
            await status(trader, gateway, orders, await accounts.find_account(email, LIVE.name))
        elif command == "arm":
            if (await check(gateway, keys)).problems:
                print("Not armed.")
                return
            account = await ensure(accounts, trader, email)
            if account is None:
                print("The futures wallet holds no USDT. Move some in first, then arm again.")
                return
            if not confirmed:
                print("Arming lets Python's money plan open real trades in this futures wallet,")
                print("within these limits, changeable on the Bot page's Settings tab:")
                for line in limits(account.profile):
                    print(f"  {line}")
                print(
                    "Every trade goes through the risk engine. Backtests are not proof of profit."
                )
                print("Run again with --yes to arm.")
                return
            await orders.set_armed(account.id, True, email, "binance_live arm")
            print("Armed. The bot opens trades from its next close, within the limits above.")
        elif command == "disarm":
            account = await accounts.find_account(email, LIVE.name)
            if account is None:
                print("The real account has not been connected yet; nothing to disarm.")
                return
            await orders.set_armed(account.id, False, email, "binance_live disarm")
            print("Disarmed. No new trades. Open trades keep their stops and targets on Binance.")
        elif command == "flatten":
            account = await accounts.find_account(email, LIVE.name)
            if account is None:
                print("The real account has not been connected yet; nothing to close.")
                return
            if not confirmed:
                print("This closes the bot's real positions at market and cancels its orders.")
                print("Your own positions and orders stay. Run again with --yes to do it.")
                return
            trades = set(await orders.open_trades(account.id))
            for record in await trader.flatten_all(trades):
                await orders.record(account.id, None, record)
                outcome = "done" if record.response is not None else f"failed: {record.error}"
                print(f"{record.symbol} {record.kind}: {outcome}")
            await status(trader, gateway, orders, account)
    finally:
        await gateway.aclose()
        await keys.aclose()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "command", choices=("keygen", "check", "status", "arm", "disarm", "flatten")
    )
    parser.add_argument("--yes", action="store_true", help="confirm arm or flatten")
    arguments = parser.parse_args()
    if arguments.command == "keygen":
        keygen(load_settings().binance_live_private_key_file)
        return
    started = time.monotonic()
    asyncio.run(run(arguments.command, arguments.yes))
    print(f"Done in {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    main()
