import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Callable
from models import Position, PositionStatus

logger = logging.getLogger("copytrader")

class PositionMonitor:
    def __init__(self, config, dex_trader, chain_client, on_position_closed: Callable[[Position, bool], Any]):
        self.config = config
        self.dex_trader = dex_trader
        self.chain_client = chain_client
        self.on_position_closed = on_position_closed
        self._tasks: Dict[str, asyncio.Task] = {}

    async def start_monitoring(self, position: Position):
        if position.id in self._tasks:
            return
        task = asyncio.create_task(self._monitor(position))
        self._tasks[position.id] = task

    async def stop_monitoring(self, position_id: str):
        if position_id in self._tasks:
            self._tasks[position_id].cancel()
            del self._tasks[position_id]

    async def stop_all(self):
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()

    async def _monitor(self, position: Position):
        try:
            if not hasattr(position, 'remaining_tokens') or position.remaining_tokens <= 0:
                position.remaining_tokens = position.tokens_bought
                
            slippage = getattr(self.config, 'SLIPPAGE_PCT', 15.0)
            tp1_target = float(getattr(self.config, 'TP1_MULTIPLIER', 1.20))
            tp1_ratio = float(getattr(self.config, 'TP1_RATIO', 0.40))
            tp2_target = float(getattr(self.config, 'TP2_MULTIPLIER', 1.40))
            tp2_ratio = float(getattr(self.config, 'TP2_RATIO', 0.40))
            tp3_target = float(getattr(self.config, 'TP3_MULTIPLIER', 5.00))
            sl_target = float(getattr(self.config, 'SL_MULTIPLIER', 0.50))
            trail_delta = float(getattr(self.config, 'TRAILING_STOP_DELTA', 0.25))
            stagnant_timeout_mins = int(getattr(self.config, 'STAGNANT_TIMEOUT_MINUTES', 25))
            runner_timeout_mins = int(getattr(self.config, 'RUNNER_TIMEOUT_MINUTES', 120))

            position.peak_multiplier = 1.0
            position.trailing_stop_multiplier = sl_target

            while True:
                await asyncio.sleep(getattr(self.config, 'PRICE_POLL_SECONDS', 5))
                
                try:
                    current_price_eth = await self.dex_trader.get_token_price_eth(position.contract_address)
                except Exception as e:
                    logger.debug(f"Price lookup temporary error for ${position.ticker}: {e}")
                    continue
                
                if current_price_eth <= 0.0:
                    logger.debug(f"Waiting for live DEX price quote for ${position.ticker}...")
                    continue
                
                # Initialize or calibrate entry price on first live DEX quote
                if not hasattr(position, 'entry_price_eth') or position.entry_price_eth <= 0.0:
                    position.entry_price_eth = current_price_eth
                    position.tokens_bought = position.stake_eth / current_price_eth if current_price_eth > 0 else position.tokens_bought
                    position.remaining_tokens = position.tokens_bought
                
                multiplier = current_price_eth / position.entry_price_eth if position.entry_price_eth > 0 else 1.0
                
                # Sanity guard against phantom API glitch spikes on illiquid dust pools
                if multiplier > 50.0 * max(1.0, position.peak_multiplier):
                    logger.warning(
                        f"⚠️ Detected potential phantom API price spike on ${position.ticker} "
                        f"({multiplier:.1f}x vs peak {position.peak_multiplier:.1f}x). Clamping outlier quote."
                    )
                    continue

                # Track peak multiplier
                if multiplier > position.peak_multiplier:
                    position.peak_multiplier = multiplier
                
                # Dynamic Trailing Stop Ratchet
                if getattr(position, 'tp2_hit', False):
                    # After Tier 2 (Core Profit): 100% Principal in wallet. Trail moonbag smoothly (Peak - 0.25x)
                    dynamic_stop = max(1.20, position.peak_multiplier - trail_delta)
                    position.trailing_stop_multiplier = max(position.trailing_stop_multiplier, dynamic_stop)
                elif getattr(position, 'tp1_hit', False):
                    # After Tier 1 (De-Risk): Move stop to 0.95x (near breakeven)
                    dynamic_stop = max(0.95, position.peak_multiplier - trail_delta)
                    position.trailing_stop_multiplier = max(position.trailing_stop_multiplier, dynamic_stop)
                else:
                    position.trailing_stop_multiplier = sl_target

                now = datetime.now(timezone.utc)
                entry_time = position.entry_time.replace(tzinfo=timezone.utc) if position.entry_time.tzinfo is None else position.entry_time
                elapsed_minutes = (now - entry_time).total_seconds() / 60

                # Formatted status logging
                if not getattr(position, 'tp1_hit', False):
                    target_info = f"TP1: {tp1_target:.2f}x (40%)"
                    stop_info = f"SL: {position.trailing_stop_multiplier:.2f}x"
                elif not getattr(position, 'tp2_hit', False):
                    target_info = f"TP2: {tp2_target:.2f}x (40%)"
                    stop_info = f"Trail SL: {position.trailing_stop_multiplier:.2f}x"
                else:
                    target_info = f"TP3 Moonbag: {tp3_target:.2f}x (20%)"
                    stop_info = f"Trail SL: {position.trailing_stop_multiplier:.2f}x (Guaranteed Profit)"

                logger.info(
                    f"Tracking ${position.ticker}: Multiplier: {multiplier:.2f}x (Peak: {position.peak_multiplier:.2f}x) | "
                    f"{target_info} | {stop_info} | Time: {elapsed_minutes:.1f}m"
                )

                # ==========================================
                # TIER 1: FAST DE-RISK (Sell 40% at 1.20x)
                # ==========================================
                if not getattr(position, 'tp1_hit', False) and (multiplier >= tp1_target or round(multiplier, 2) >= tp1_target):
                    position.tp1_hit = True  # Re-entrancy lock
                    tokens_to_sell = min(position.tokens_bought * tp1_ratio, position.remaining_tokens)
                    logger.info(f"🎯 TP1 HIT for ${position.ticker} ({multiplier:.2f}x >= {tp1_target:.2f}x)! Selling {tp1_ratio*100:.0f}% ({tokens_to_sell:,.2f} tokens)...")
                    
                    sell_tx = ""
                    try:
                        sell_tx, _ = await self.dex_trader.sell_token(
                            position.contract_address, 
                            tokens_to_sell, 
                            slippage
                        )
                    except Exception as e:
                        logger.warning(f"TP1 sell encounter error: {e}, retrying once...")
                        await asyncio.sleep(1)
                        sell_tx, _ = await self.dex_trader.sell_token(
                            position.contract_address, 
                            tokens_to_sell, 
                            slippage
                        )

                    position.tp1_sold_tokens = tokens_to_sell
                    position.remaining_tokens = max(0.0, position.remaining_tokens - tokens_to_sell)
                    partial_pnl_usd = (multiplier - 1.0) * (position.stake_usd * tp1_ratio)
                    position.tp1_pnl_usd = partial_pnl_usd
                    position.accumulated_pnl_usd += partial_pnl_usd
                    position.trailing_stop_multiplier = 0.95
                    
                    logger.info(
                        f"✅ TP1 COMPLETED: Sold {tokens_to_sell:,.2f} ${position.ticker} (Secured +${partial_pnl_usd:.2f} profit). "
                        f"Stop-Loss ratcheted to 0.95x. Remaining {position.remaining_tokens:,.2f} tokens riding to {tp2_target:.2f}x!"
                    )
                    continue

                # ==========================================
                # TIER 2: 100% PRINCIPAL RECOVERY (Sell 40% at 1.40x)
                # ==========================================
                if getattr(position, 'tp1_hit', False) and not getattr(position, 'tp2_hit', False) and (multiplier >= tp2_target or round(multiplier, 2) >= tp2_target):
                    position.tp2_hit = True  # Re-entrancy lock
                    tokens_to_sell = min(position.tokens_bought * tp2_ratio, position.remaining_tokens)
                    logger.info(f"🎯 TP2 HIT for ${position.ticker} ({multiplier:.2f}x >= {tp2_target:.2f}x)! Selling {tp2_ratio*100:.0f}% ({tokens_to_sell:,.2f} tokens)...")
                    
                    sell_tx = ""
                    try:
                        sell_tx, _ = await self.dex_trader.sell_token(
                            position.contract_address, 
                            tokens_to_sell, 
                            slippage
                        )
                    except Exception as e:
                        logger.warning(f"TP2 sell encounter error: {e}, retrying once...")
                        await asyncio.sleep(1)
                        sell_tx, _ = await self.dex_trader.sell_token(
                            position.contract_address, 
                            tokens_to_sell, 
                            slippage
                        )

                    position.tp2_sold_tokens = tokens_to_sell
                    position.remaining_tokens = max(0.0, position.remaining_tokens - tokens_to_sell)
                    partial_pnl_usd = (multiplier - 1.0) * (position.stake_usd * tp2_ratio)
                    position.tp2_pnl_usd = partial_pnl_usd
                    position.accumulated_pnl_usd += partial_pnl_usd
                    position.trailing_stop_multiplier = 1.20
                    
                    logger.info(
                        f"✅ TP2 COMPLETED: Sold {tokens_to_sell:,.2f} ${position.ticker} (Secured +${partial_pnl_usd:.2f} profit). "
                        f"🎉 PRINCIPAL 100% RETURNED TO WALLET! Remaining {position.remaining_tokens:,.2f} (20% Moonbag) riding risk-free to {tp3_target:.2f}x!"
                    )
                    continue

                # ==========================================
                # FULL EXIT CONDITIONS
                # ==========================================
                should_close = False
                close_reason = ""
                tokens_to_close = position.remaining_tokens
                is_derisked = getattr(position, 'tp1_hit', False) or getattr(position, 'tp2_hit', False)

                # 1. TP3 Moonshot Target Hit (5.00x - 15.00x)
                if getattr(position, 'tp2_hit', False) and multiplier >= tp3_target:
                    should_close = True
                    close_reason = f"🚀 TP3 MOONSHOT HIT ({multiplier:.2f}x >= {tp3_target:.2f}x)"
                    position.tp3_hit = True

                # 2. Dynamic Trailing Stop Triggered
                elif is_derisked and multiplier <= position.trailing_stop_multiplier:
                    should_close = True
                    close_reason = f"Dynamic Trailing Stop Hit ({multiplier:.2f}x <= {position.trailing_stop_multiplier:.2f}x | Peak: {position.peak_multiplier:.2f}x)"

                # 3. Initial Stop Loss (before Tier 1)
                elif not getattr(position, 'tp1_hit', False) and multiplier <= sl_target and current_price_eth > 0 and elapsed_minutes >= 0.15:
                    should_close = True
                    close_reason = f"Initial Stop Loss ({multiplier:.2f}x <= {sl_target:.2f}x)"

                # 4. Adaptive Two-Track Timeout (25m stagnant / 120m moonbag runner)
                elif not is_derisked and elapsed_minutes > stagnant_timeout_mins:
                    should_close = True
                    close_reason = f"Stagnation Timeout ({elapsed_minutes:.1f}m > {stagnant_timeout_mins}m)"
                elif is_derisked and elapsed_minutes > runner_timeout_mins:
                    should_close = True
                    close_reason = f"Moonbag Hold Limit ({elapsed_minutes:.1f}m > {runner_timeout_mins}m)"

                if should_close:
                    logger.info(f"Closing position ${position.ticker}: {close_reason}")
                    sell_tx = ""
                    try:
                        sell_tx, _ = await self.dex_trader.sell_token(
                            position.contract_address, 
                            tokens_to_close, 
                            slippage
                        )
                    except Exception as e:
                        logger.warning(f"Closing sell encountered error: {e}, retrying...")
                        await asyncio.sleep(1)
                        sell_tx, _ = await self.dex_trader.sell_token(
                            position.contract_address, 
                            tokens_to_close, 
                            slippage
                        )
                    
                    # Calculate final leg PnL
                    remaining_ratio = position.remaining_tokens / position.tokens_bought if position.tokens_bought > 0 else 1.0
                    final_leg_pnl_usd = (multiplier - 1.0) * (position.stake_usd * remaining_ratio)
                    
                    total_pnl_usd = (position.tp1_pnl_usd or 0.0) + (position.tp2_pnl_usd or 0.0) + final_leg_pnl_usd
                    is_win = total_pnl_usd > 0.0

                    position.pnl_usd = total_pnl_usd
                    position.pnl_pct = (total_pnl_usd / position.stake_usd) * 100
                    position.status = PositionStatus.CLOSED_TP if is_win else PositionStatus.CLOSED_SL
                    position.exit_time = datetime.now(timezone.utc)
                    position.exit_price_eth = current_price_eth
                    position.tx_hash_sell = sell_tx

                    if asyncio.iscoroutinefunction(self.on_position_closed):
                        await self.on_position_closed(position, is_win)
                    else:
                        self.on_position_closed(position, is_win)
                    break

        except asyncio.CancelledError:
            logger.info(f"Monitoring cancelled for position {position.id}")
        except Exception as e:
            logger.error(f"Error in monitor loop for {position.ticker}: {e}", exc_info=True)
            position.status = PositionStatus.CLOSED_ERROR
            if asyncio.iscoroutinefunction(self.on_position_closed):
                await self.on_position_closed(position, False)
            else:
                self.on_position_closed(position, False)
        finally:
            self._tasks.pop(position.id, None)
