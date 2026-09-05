import asyncio
import signal
import sys
import time
import logging

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
from config import Config
from logger_setup import setup_logging
from models import CallSignal, Position, PositionStatus, StrategyState
from message_parser import MessageParser
from telegram_listener import TelegramListener
from chain_client import ChainClient
from dex_trader import DexTrader
from strategy_engine import StrategyEngine
from position_monitor import PositionMonitor

class CopyTraderBot:
    def __init__(self):
        setup_logging()
        self.logger = logging.getLogger("copytrader")
        self.config = Config()
        self.parser = MessageParser()
        
        self.chain_client = ChainClient(self.config)
        self.dex_trader = DexTrader(self.chain_client, self.config)
        self.strategy_engine = StrategyEngine(self.config)
        self.position_monitor = PositionMonitor(
            self.config, 
            self.dex_trader, 
            self.chain_client, 
            self.on_position_closed
        )
        self.telegram_listener = TelegramListener(
            self.config, 
            self.parser, 
            self.on_signal
        )
        
    async def start(self):
        banner = f"""
╔══════════════════════════════════════════════════╗
║     ROBINHOOD CHAIN COPY-TRADER BOT v1.0        ║
╠══════════════════════════════════════════════════╣
║  Mode:     {'DRY RUN (Paper Trading)' if self.config.DRY_RUN else 'LIVE TRADING (Real Money)'}              ║
║  Capital:  ${self.config.INITIAL_CAPITAL_USD:.2f} USD (Floor: ${self.config.SAFETY_FLOOR_USD:.2f})            ║
║  Strategy: 2-Step Compound (${self.config.BASELINE_STAKE_USD:.0f}/${self.config.COMPOUND_STAKE_USD:.0f})               ║
║  Ladder:   40% @ {self.config.TP1_MULTIPLIER:.2f}x | 40% @ {self.config.TP2_MULTIPLIER:.2f}x | 20% Moonbag 🚀║
║  Shield:   Dynamic Trailing Stop (-0.25x)        ║
║  Timeouts: 25m Stagnant / 120m Moonbag Hold      ║
║  Channel:  {self.config.CHANNEL_USERNAME}                       ║
╚══════════════════════════════════════════════════╝
        """
        print(banner)
        self.logger.info("Initializing copy-trader components...")
        
        await self.dex_trader.initialize()
        
        eth_balance = await self.chain_client.get_eth_balance()
        eth_price = await self.chain_client.get_eth_price_usd()
        usd_value = eth_balance * eth_price
        
        self.logger.info(f"Wallet Balance: {eth_balance:.4f} ETH (${usd_value:.2f} USD) @ ${eth_price:.2f}/ETH")
        
        if not self.config.DRY_RUN and usd_value < self.config.INITIAL_CAPITAL_USD:
            self.logger.warning(
                f"LIVE MODE WARNING: Balance (${usd_value:.2f}) is below initial capital target (${self.config.INITIAL_CAPITAL_USD:.2f})!"
            )
            
        self.logger.info("Connecting to Telegram channel listener...")
        await self.telegram_listener.start()

    async def on_signal(self, signal: CallSignal):
        start_time = time.time()
        self.logger.info(f"==> Incoming Signal: ${signal.ticker} (DEX: {signal.dex})")
        if not signal.contract_address:
            self.logger.warning(f"Skipping ${signal.ticker}: No contract address identified.")
            return

        eth_price = await self.chain_client.get_eth_price_usd()
        decision = self.strategy_engine.get_trade_decision(signal, eth_price)
        
        if not decision.should_trade:
            self.logger.info(f"Skipping trade for ${signal.ticker}: {decision.reason}")
            return
            
        self.logger.info(
            f"Executing BUY for ${signal.ticker}: Stake ${decision.stake_usd:.2f} "
            f"({decision.stake_eth:.5f} ETH) | State: {decision.state.value}"
        )
        
        try:
            tx_hash, tokens_bought = await self.dex_trader.buy_token(
                signal.contract_address, 
                decision.stake_eth, 
                self.config.SLIPPAGE_PCT,
                start_time=start_time
            )
            
            if tokens_bought <= 0:
                self.logger.error(f"Buy failed for ${signal.ticker}: 0 tokens received.")
                return
            
            position = Position(
                ticker=signal.ticker,
                contract_address=signal.contract_address,
                entry_price_eth=decision.stake_eth / tokens_bought if tokens_bought > 0 else 0.0,
                entry_price_usd=decision.stake_usd / tokens_bought if tokens_bought > 0 else 0.0,
                tokens_bought=tokens_bought,
                stake_usd=decision.stake_usd,
                stake_eth=decision.stake_eth,
                tx_hash_buy=tx_hash,
                status=PositionStatus.OPEN
            )
            
            self.strategy_engine.add_position(position)
            await self.position_monitor.start_monitoring(position)
            self.logger.info(f"Position opened: {position.id} for ${position.ticker} ({tokens_bought:,.2f} tokens)")
            
        except Exception as e:
            self.logger.error(f"Trade execution exception for ${signal.ticker}: {e}", exc_info=True)

    async def on_position_closed(self, position: Position, is_win: bool):
        self.strategy_engine.remove_position(position.id)
        self.strategy_engine.record_trade_result(position, is_win)
        
        pnl = position.pnl_usd or 0.0
        self.logger.info(
            f"Position closed: ${position.ticker} | Win: {is_win} | PnL: ${pnl:+.2f} | "
            f"New Balance: ${self.strategy_engine.balance_usd:.2f} | Next State: {self.strategy_engine.state.value}"
        )
        
        if self.strategy_engine.state == StrategyState.HALTED:
            self.logger.critical("CIRCUIT BREAKER TRIGGERED ($40 Floor Reached). All further trading is HALTED.")
            
    async def shutdown(self):
        self.logger.info("Shutting down bot...")
        await self.position_monitor.stop_all()
        await self.telegram_listener.stop()
        report = self.strategy_engine.get_status_report()
        self.logger.info(f"Final Session Summary: {report}")

async def main():
    bot = CopyTraderBot()
    try:
        await bot.start()
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nStopping bot...")
    finally:
        await bot.shutdown()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
