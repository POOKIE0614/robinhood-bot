from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List
import uuid

class StrategyState(Enum):
    BASELINE = "baseline"
    COMPOUND = "compound"
    HALTED = "halted"

class PositionStatus(Enum):
    OPEN = "open"
    CLOSED_TP = "closed_tp"
    CLOSED_SL = "closed_sl"
    CLOSED_TIMEOUT = "closed_timeout"
    CLOSED_MANUAL = "closed_manual"
    CLOSED_ERROR = "closed_error"

@dataclass
class CallSignal:
    ticker: str
    contract_address: Optional[str]
    mcap_usd: Optional[float]
    liquidity_usd: Optional[float]
    liquidity_pct: Optional[float]
    buy_tax: float
    sell_tax: float
    token_age_minutes: Optional[int]
    holders: Optional[int]
    volume_24h: Optional[float]
    swaps_5m: Optional[int]
    elite_wallets: int
    good_wallets: int
    dex: str
    raw_text: str
    timestamp: datetime
    message_id: int

@dataclass
class Position:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    ticker: str = ""
    contract_address: str = ""
    entry_price_eth: float = 0.0
    entry_price_usd: float = 0.0
    tokens_bought: float = 0.0
    stake_usd: float = 0.0
    stake_eth: float = 0.0
    entry_time: datetime = field(default_factory=datetime.utcnow)
    tx_hash_buy: str = ""
    status: PositionStatus = PositionStatus.OPEN
    tp1_hit: bool = False
    tp1_sold_tokens: float = 0.0
    tp1_pnl_usd: float = 0.0
    tp2_hit: bool = False
    tp2_sold_tokens: float = 0.0
    tp2_pnl_usd: float = 0.0
    tp3_hit: bool = False
    peak_multiplier: float = 1.0
    trailing_stop_multiplier: float = 0.50
    remaining_tokens: float = 0.0
    accumulated_pnl_usd: float = 0.0
    exit_price_eth: Optional[float] = None
    exit_price_usd: Optional[float] = None
    exit_time: Optional[datetime] = None
    tx_hash_sell: Optional[str] = None
    pnl_usd: Optional[float] = None
    pnl_pct: Optional[float] = None

    def close(self, status: PositionStatus, exit_price_eth: float, exit_price_usd: float, tx_hash_sell: str, pnl_usd: float, pnl_pct: float):
        self.status = status
        self.exit_price_eth = exit_price_eth
        self.exit_price_usd = exit_price_usd
        self.tx_hash_sell = tx_hash_sell
        self.exit_time = datetime.utcnow()
        self.pnl_usd = pnl_usd
        self.pnl_pct = pnl_pct

@dataclass
class TradeDecision:
    should_trade: bool
    stake_usd: float
    stake_eth: float
    state: StrategyState
    reason: str
