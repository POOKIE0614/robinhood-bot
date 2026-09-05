import os
import sys
import json
import logging
import asyncio
import time
import aiohttp
from typing import Tuple, Dict, Any, Optional
from web3 import Web3
import eth_abi

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

logger = logging.getLogger("copytrader")

from stock_v4_routes import (
    StockV4Router,
    STOCK_TOKENS as EXTENDED_STOCK_TOKENS,
    STOCK_LIST as EXTENDED_STOCK_LIST,
    fetch_dexscreener,
    map_ds_pair,
    pool_id_from_key,
)

# =============== STOCK TOKENS (Robinhood Chain) ===============
STOCK_TOKENS = EXTENDED_STOCK_TOKENS
STOCK_LIST = EXTENDED_STOCK_LIST

WETH = Web3.to_checksum_address("0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73")
USDG = Web3.to_checksum_address("0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168")
UNIVERSAL_ROUTER = Web3.to_checksum_address("0x8876789976dEcBfCbBbe364623C63652db8C0904")
ZERO = "0x0000000000000000000000000000000000000000"

# ─── Hardcoded Addresses (Per Specification) ──────────────────────────────
WETH_ADDRESS            = "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73"
USDG_ADDRESS            = "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168"
PERMIT2_ADDRESS         = "0x000000000022D473030F116dDEE9F6B43aC78BA3"
UNIVERSAL_ROUTER_ADDR   = "0x8876789976dEcBfCbBbe364623C63652db8C0904"

UNISWAP_V2_FACTORY      = "0x8bcEaA40B9AcdfAedF85AdF4FF01F5Ad6517937f"
UNISWAP_V2_ROUTER       = "0x89e5DB8B5aA49aA85AC63f691524311AEB649eba"
UNISWAP_V3_FACTORY      = "0x1f7d7550B1b028f7571E69A784071F0205FD2EfA"
UNISWAP_V3_SWAPROUTER02 = "0xCaf681a66D020601342297493863E78C959E5cb2"
UNISWAP_V3_POS_MGR     = "0x73991a25C818Bf1f1128dEAaB1492D45638DE0D3"
UNISWAP_V3_QUOTER_V2   = "0x33e885eD0Ec9bF04EcfB19341582aADCb4c8A9E7"
UNISWAP_V4_POOL_MGR     = "0x8366a39CC670B4001A1121B8F6A443A643e40951"
UNISWAP_V4_STATE_VIEW   = "0xF3334192D15450CdD385c8B70e03F9A6bD9E673b"
UNISWAP_V4_QUOTER       = "0x8Dc178eFB8111BB0973Dd9d722ebeFF267c98F94"
UNISWAP_V4_POS_MGR     = "0x58daec3116aae6D93017bAAea7749052E8a04fA7"

PONS_V2_FACTORY         = "0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e"
PONS_V2_HOOK            = "0xe5e702641ea86f4ae6cc3cdaed2b886f976be044"
PONS_V1_FACTORY         = "0xA5aAb3F0c6EeadF30Ef1D3Eb997108E976351feB"
BAGS_FACTORY            = "0xe8Cc4431adF8b5A847C113EF0c6af9043219Cb37"
BAGS_LENS               = "0xC82Db941dAf90B754aecb5F7D14c683dc608d595"
BAGS_HOOK               = "0x2380aBf72C17aABAb76480244759AC7E2932EEcC"

PONS_LAUNCHED_TOPIC     = "0x8d4aad4953d0ca700d468f3753aa14432d1b35b43ec6409f051fb6aa43a89607"

# ─── ABIs ───────────────────────────────────────────────────────────────
ERC20_ABI = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]

V3_FACTORY_ABI = [
    {"inputs": [{"name": "tokenA", "type": "address"}, {"name": "tokenB", "type": "address"}, {"name": "fee", "type": "uint24"}], "name": "getPool", "outputs": [{"name": "pool", "type": "address"}], "stateMutability": "view", "type": "function"}
]

V2_FACTORY_ABI = [
    {"inputs": [{"name": "tokenA", "type": "address"}, {"name": "tokenB", "type": "address"}], "name": "getPair", "outputs": [{"name": "pair", "type": "address"}], "stateMutability": "view", "type": "function"}
]

BAGS_LENS_ABI = [
    {"inputs": [{"name": "token", "type": "address"}], "name": "getTokenState", "outputs": [{"name": "curve", "type": "address"}, {"name": "migrated", "type": "bool"}], "stateMutability": "view", "type": "function"}
]

STATE_VIEW_ABI = [
    {
        "inputs": [{"name": "poolId", "type": "bytes32"}],
        "name": "getSlot0",
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "protocolFee", "type": "uint24"},
            {"name": "lpFee", "type": "uint24"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"name": "poolId", "type": "bytes32"}],
        "name": "getLiquidity",
        "outputs": [{"name": "", "type": "uint128"}],
        "stateMutability": "view",
        "type": "function"
    }
]

UNIVERSAL_ROUTER_ABI = [
    {
        "name": "execute",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {"name": "commands", "type": "bytes"},
            {"name": "inputs",   "type": "bytes[]"},
            {"name": "deadline", "type": "uint256"}
        ],
        "outputs": []
    }
]

SWAP_ROUTER02_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "recipient", "type": "address"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMinimum", "type": "uint256"},
                    {"name": "sqrtPriceLimitX96", "type": "uint160"}
                ],
                "name": "params",
                "type": "tuple"
            }
        ],
        "name": "exactInputSingle",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [
            {
                "components": [
                    {"name": "path", "type": "bytes"},
                    {"name": "recipient", "type": "address"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMinimum", "type": "uint256"}
                ],
                "name": "params",
                "type": "tuple"
            }
        ],
        "name": "exactInput",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function"
    }
]

V2_ROUTER_ABI = [
    {"inputs": [{"name": "amountOutMin", "type": "uint256"}, {"name": "path", "type": "address[]"}, {"name": "to", "type": "address"}, {"name": "deadline", "type": "uint256"}], "name": "swapExactETHForTokensSupportingFeeOnTransferTokens", "outputs": [], "stateMutability": "payable", "type": "function"}
]

PONS_CURVE_ABI = [
    {"inputs": [{"name": "quoteIn", "type": "uint256"}, {"name": "minTokensOut", "type": "uint256"}, {"name": "recipient", "type": "address"}], "name": "buy", "outputs": [{"name": "tokensReceived", "type": "uint256"}], "stateMutability": "payable", "type": "function"},
    {"inputs": [{"name": "amount", "type": "uint256"}, {"name": "minQuoteOut", "type": "uint256"}, {"name": "recipient", "type": "address"}], "name": "sell", "outputs": [{"name": "quoteReceived", "type": "uint256"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [], "name": "graduated", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "pairToken", "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"}
]


def make_v4_swap_input(token_in: str, token_out: str, amount_in: int, min_out: int, recipient: str, fee: int = 3000, tick_spacing: int = 60, hook_addr: str = "0x" + "0"*40, w3: Optional[Web3] = None) -> bytes:
    """
    Corrected V4 swap input encoder incorporating:
    1. 7-field ExactInputSingleParams struct (including minHopPriceX36 = 0)
    2. SETTLE_ALL for actual input token (token_in)
    3. TAKE_ALL with 2 parameters (token_out, min_out)
    """
    c0 = Web3.to_checksum_address(token_in)
    c1 = Web3.to_checksum_address(token_out)

    if int(c0, 16) < int(c1, 16):
        currency0, currency1 = c0, c1
        zero_for_one = True
    else:
        currency0, currency1 = c1, c0
        zero_for_one = False

    pool_key = (currency0, currency1, fee, tick_spacing, Web3.to_checksum_address(hook_addr))

    # Action 0x06: ExactInputSingleParams with 7 fields (including minHopPriceX36 = 0)
    param0 = eth_abi.encode(
        [
            '(address,address,uint24,int24,address)',  # poolKey
            'bool',     # zeroForOne
            'uint128',  # amountIn
            'uint128',  # amountOutMinimum
            'uint160',  # sqrtPriceLimitX96
            'uint256',  # minHopPriceX36
            'bytes'     # hookData
        ],
        [
            pool_key,
            zero_for_one,
            amount_in,
            min_out,
            0,          # sqrtPriceLimitX96 = 0
            0,          # minHopPriceX36 = 0
            b''         # hookData = b''
        ]
    )

    # Action 0x0c: SETTLE_ALL params -> settles actual input token (token_in)
    param1 = eth_abi.encode(['address', 'uint256'], [Web3.to_checksum_address(token_in), amount_in])

    # Action 0x0f: TAKE_ALL params -> 2 parameters (token_out, min_out)
    param2 = eth_abi.encode(['address', 'uint256'], [Web3.to_checksum_address(token_out), min_out])

    actions = bytes([0x06, 0x0c, 0x0f])
    return eth_abi.encode(['bytes', 'bytes[]'], [actions, [param0, param1, param2]])


def get_price_eth_dexscreener(token: str) -> float:
    import requests
    try:
        r = requests.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{token}",
            timeout=3,
        )
        pairs = (r.json() or {}).get("pairs") or []
        rh = [p for p in pairs if str(p.get("chainId", "")).lower() in ("robinhood", "robinhoodchain")]
        if not rh:
            rh = pairs
        if not rh:
            return 0.0
        p = max(rh, key=lambda x: float(x.get("liquidity", {}).get("usd") or 0))
        native = p.get("priceNative")
        if native:
            return float(native)
        usd = float(p.get("priceUsd") or 0)
        return usd / 2450.0 if usd else 0.0  # rough ETH usd; replace with your live ETH price if you have it
    except Exception:
        return 0.0


class DexTrader:
    def __init__(self, chain_client, config):
        self.chain = chain_client
        self.config = config
        self.w3 = self.chain.w3

        self.weth_address       = self.w3.to_checksum_address(WETH_ADDRESS)
        self.usdg_address       = self.w3.to_checksum_address(USDG_ADDRESS)
        self.uni_router_address = self.w3.to_checksum_address(UNIVERSAL_ROUTER_ADDR)
        self.swap_router02_addr = self.w3.to_checksum_address(UNISWAP_V3_SWAPROUTER02)

        self.v3_factory = self.w3.eth.contract(address=self.w3.to_checksum_address(UNISWAP_V3_FACTORY), abi=V3_FACTORY_ABI)
        self.v2_factory = self.w3.eth.contract(address=self.w3.to_checksum_address(UNISWAP_V2_FACTORY), abi=V2_FACTORY_ABI)
        self.bags_lens  = self.w3.eth.contract(address=self.w3.to_checksum_address(BAGS_LENS), abi=BAGS_LENS_ABI)
        self.uni_router = self.w3.eth.contract(address=self.uni_router_address, abi=UNIVERSAL_ROUTER_ABI)
        self.router02   = self.w3.eth.contract(address=self.swap_router02_addr, abi=SWAP_ROUTER02_ABI)
        self.v2_router  = self.w3.eth.contract(address=self.w3.to_checksum_address(UNISWAP_V2_ROUTER), abi=V2_ROUTER_ABI)
        self.state_view = self.w3.eth.contract(address=self.w3.to_checksum_address(UNISWAP_V4_STATE_VIEW), abi=STATE_VIEW_ABI)
        self.stock_v4   = StockV4Router(self.w3, self.chain.account if hasattr(self.chain, 'account') else None)

        # Venues with pre-flight simulation disabled (Default: only LAUNCHPAD_CURVE_ETH)
        self.no_sim_venues = {"LAUNCHPAD_CURVE_ETH"}

        # O(1) Route Cache: once a token's venue/route is resolved, never re-run
        # the full detection cascade (incl. DexScreener + on-chain probes) for it
        # again on every price poll. Only successful (non-"NONE") results are
        # cached so a token that hasn't graduated/launched yet keeps retrying.
        self._route_cache: Dict[str, Tuple[str, str, str, int]] = {}

        # V4 Pool Params Cache: stores {token_cs: {"tick": int, "hook": str}}
        # Populated when DexScreener resolves a V4 pair so buy_token / sell_token
        # can use the real tick spacing + hook instead of hardcoded defaults.
        self._v4_pool_params_cache: Dict[str, dict] = {}

        # O(1) Token Curve Cache
        self._curve_cache_file = os.path.join(os.path.dirname(__file__), "cache", "curve_cache.json")
        self._load_curve_cache()

    def _load_curve_cache(self):
        self._curve_cache: Dict[str, Tuple[Optional[str], str]] = {
            self.w3.to_checksum_address("0x77f06AEE8aB51cF6347fA599D13cB6B97C53d4B6"): (self.w3.to_checksum_address("0x1DB4E3fE3f941e4c19Cf87488dC653D8E9D6Dae4"), self.usdg_address),
            self.w3.to_checksum_address("0x928233827A025193A553DC805ADE16174Be7589f"): (self.w3.to_checksum_address("0x35fe208A3F5400016E3E9C409bb9752cB596D2Dd"), "0x" + "0"*40)
        }
        try:
            if os.path.exists(self._curve_cache_file):
                with open(self._curve_cache_file, "r", encoding="utf-8") as f:
                    disk_cache = json.load(f)
                    for k, v in disk_cache.items():
                        c_addr = self.w3.to_checksum_address(v[0]) if v[0] else None
                        p_tok = self.w3.to_checksum_address(v[1]) if v[1] else "0x" + "0"*40
                        self._curve_cache[self.w3.to_checksum_address(k)] = (c_addr, p_tok)
        except Exception as e:
            logger.debug(f"Curve cache load warning: {e}")

    def _save_curve_cache(self):
        try:
            os.makedirs(os.path.dirname(self._curve_cache_file), exist_ok=True)
            data = {k: list(v) for k, v in self._curve_cache.items()}
            with open(self._curve_cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.debug(f"Curve cache save warning: {e}")

    async def initialize(self):
        logger.info(f"Initialized DexTrader on Chain ID 4663 with Universal Router: {self.uni_router_address}")

    async def verify_chain_id(self):
        if getattr(self, '_chain_id_verified', False):
            return
        chain_id = await asyncio.to_thread(lambda: self.w3.eth.chain_id)
        if chain_id != 4663:
            raise RuntimeError(f"Chain ID mismatch! Expected 4663, got {chain_id}")
        self._chain_id_verified = True

    # ─── O(1) Token Curve Resolution & Graduated Check ──────────────────

    async def resolve_token_curve(self, token_address: str) -> Tuple[Optional[str], str, bool]:
        """
        Ultra-Fast O(1) Curve Resolution:
        1. Cache Hit: O(1) in-memory lookup -> single graduated() view call.
        2. Cache Miss Step 1: Direct token.curve() view call on token contract (Pons standard, <50ms).
        3. Cache Miss Step 2: Bags Lens getTokenState() view call fallback.
        4. Cache Miss Step 3: Fast 300-block event query on fallback RPC.
        """
        token_cs = self.w3.to_checksum_address(token_address)

        # 1. Cache Hit -> O(1) lookup
        if token_cs in self._curve_cache:
            c_addr, p_tok = self._curve_cache[token_cs]
            if not c_addr:
                return None, "0x" + "0"*40, False
            is_grad = False
            try:
                grad_sel = self.w3.keccak(text="graduated()")[:4]
                res = await asyncio.to_thread(self.w3.eth.call, {'to': c_addr, 'data': grad_sel})
                is_grad = bool(int(res.hex(), 16))
            except Exception:
                pass
            if is_grad:
                self._curve_cache[token_cs] = (None, p_tok)
                self._save_curve_cache()
                return None, p_tok, True
            return c_addr, p_tok, False

        # 2. Cache Miss Step 1: Direct token.curve() method (Direct O(1) view call on Pons token)
        try:
            curve_sel = self.w3.keccak(text="curve()")[:4].hex()
            res = await asyncio.wait_for(
                asyncio.to_thread(self.w3.eth.call, {'to': token_cs, 'data': curve_sel}),
                timeout=1.0
            )
            raw_addr = res.hex()
            if len(raw_addr) >= 40 and raw_addr[-40:] != "0"*40:
                c_addr = self.w3.to_checksum_address('0x' + raw_addr[-40:])
                p_tok = "0x" + "0"*40
                is_grad = False
                try:
                    pair_sel = self.w3.keccak(text="pairToken()")[:4].hex()
                    pair_res = await asyncio.to_thread(self.w3.eth.call, {'to': c_addr, 'data': pair_sel})
                    if len(pair_res.hex()) >= 40:
                        p_tok = self.w3.to_checksum_address('0x' + pair_res.hex()[-40:])
                except Exception:
                    pass

                try:
                    grad_sel = self.w3.keccak(text="graduated()")[:4].hex()
                    grad_res = await asyncio.to_thread(self.w3.eth.call, {'to': c_addr, 'data': grad_sel})
                    is_grad = bool(int(grad_res.hex(), 16))
                except Exception:
                    pass

                if not is_grad:
                    self._curve_cache[token_cs] = (c_addr, p_tok)
                    self._save_curve_cache()
                    return c_addr, p_tok, False
                else:
                    self._curve_cache[token_cs] = (None, p_tok)
                    self._save_curve_cache()
                    return None, p_tok, True
        except Exception:
            pass

        # 3. Cache Miss Step 2: Try Bags Lens second (0.6s fast timeout)
        try:
            curve_addr, migrated = await asyncio.wait_for(
                asyncio.to_thread(self.bags_lens.functions.getTokenState(token_cs).call),
                timeout=0.6
            )
            if curve_addr and curve_addr != '0x' + '0'*40:
                c_addr = self.w3.to_checksum_address(curve_addr)
                if not migrated:
                    self._curve_cache[token_cs] = (c_addr, "0x" + "0"*40)
                    self._save_curve_cache()
                    return c_addr, "0x" + "0"*40, False
                else:
                    self._curve_cache[token_cs] = (None, "0x" + "0"*40)
                    self._save_curve_cache()
                    return None, "0x" + "0"*40, True
        except Exception:
            pass

        # 4. Cache Miss Step 3: Check Pons Factory TokenLaunched event on fallback RPC (50 blocks)
        try:
            fallback = getattr(self.chain, 'fallback_w3', self.w3)
            token_topic = '0x' + token_cs[2:].lower().zfill(64)
            latest_blk = await asyncio.to_thread(lambda: fallback.eth.block_number)
            from_blk = max(0, latest_blk - 50)
            logs = await asyncio.wait_for(
                asyncio.to_thread(
                    fallback.eth.get_logs,
                    {
                        'fromBlock': from_blk,
                        'toBlock': 'latest',
                        'address': self.w3.to_checksum_address(PONS_V2_FACTORY),
                        'topics': [PONS_LAUNCHED_TOPIC, token_topic]
                    }
                ),
                timeout=1.5
            )
            if logs:
                lg = logs[0]
                c_addr = self.w3.to_checksum_address('0x' + lg['topics'][2].hex()[-40:])
                data_hex = lg['data'].hex() if hasattr(lg['data'], 'hex') else str(lg['data'])
                p_tok = "0x" + "0"*40
                if len(data_hex) >= 64:
                    p_tok = self.w3.to_checksum_address('0x' + data_hex[:64][-40:])

                is_grad = False
                try:
                    grad_sel = self.w3.keccak(text='graduated()')[:4].hex()
                    res = await asyncio.to_thread(self.w3.eth.call, {'to': c_addr, 'data': grad_sel})
                    is_grad = bool(int(res.hex(), 16))
                except Exception:
                    pass

                if not is_grad:
                    self._curve_cache[token_cs] = (c_addr, p_tok)
                    self._save_curve_cache()
                    return c_addr, p_tok, False
                else:
                    self._curve_cache[token_cs] = (None, p_tok)
                    self._save_curve_cache()
                    return None, p_tok, True
        except Exception as e:
            logger.debug(f"Pons V2 event query failed for {token_cs}: {e}")

        # Mark miss in cache to avoid repeated checks
        self._curve_cache[token_cs] = (None, "0x" + "0"*40)
        return None, "0x" + "0"*40, False

    async def is_contract(self, address: str) -> bool:
        """Quick check if address is a smart contract"""
        try:
            code = await self.chain._retry(
                self.w3.eth.get_code, 
                self.w3.to_checksum_address(address)
            )
            return code not in (b'', b'0x', '0x', None, '')
        except Exception:
            return False

    # ─── Fast On-Chain Decision Tree ────────────────────────────────────

    async def detect_venue_and_route(self, token_address: str) -> Tuple[str, str, str, int]:
        """
        Cached front-door for venue detection. Once a token resolves to a real
        venue, that result is reused for the rest of the run instead of
        re-running the whole detection cascade (DexScreener + on-chain probes)
        on every call — this matters a lot because get_token_price_eth() calls
        this on every price-poll tick for every open position.
        """
        token_cs = self.w3.to_checksum_address(token_address)
        cached = self._route_cache.get(token_cs)
        if cached is not None:
            return cached

        result = await self._detect_venue_and_route_uncached(token_cs)
        if result[0] != "NONE":
            self._route_cache[token_cs] = result
        return result

    async def _detect_venue_and_route_uncached(self, token_address: str) -> Tuple[str, str, str, int]:
        """
        Fast Decision Tree (Stops immediately on first valid match):
        0. Fast Check: Verify address is a smart contract (skip EOAs)
        1. Check Bonding Curve (Pons token.curve() / Bags) -> return immediately if not graduated
        2. Check Uniswap V3 WETH & USDG in parallel (requires live liquidity > 0)
        3. Check Stock Token Pools (V3/V4 pools with TTWO, TSLA, PLTR, etc.)
        4. Check Uniswap V2 in parallel
        5. Return NONE
        """
        await self.verify_chain_id()
        token_cs = self.w3.to_checksum_address(token_address)

        # ========== FAST FILTER: EOA vs Smart Contract ==========
        if not await self.is_contract(token_cs):
            logger.info(f"⏩ Skipping {token_cs} — not a contract (EOA)")
            print(f"⏩ Skipping {token_cs} — not a contract (EOA)")
            return "NONE", ZERO, self.weth_address, 0
        # ========================================================

        # ========== 0. ULTRA-FAST DEXSCREENER CHECK (~150ms) ==========
        # IMPORTANT: fetch_dexscreener() uses blocking `requests`, not aiohttp.
        # Never call it directly in an async function - it freezes the whole
        # event loop (including the Telegram listener) for the length of the
        # HTTP call. Always push it to a thread, with a hard timeout so a slow
        # DexScreener response can't stall detection for long.
        try:
            ds_pair = await asyncio.wait_for(
                asyncio.to_thread(fetch_dexscreener, token_cs),
                timeout=5.0
            )
            if ds_pair:
                mapped = map_ds_pair(token_cs, ds_pair, self.w3)
                if mapped.get("venue") != "NONE":
                    # Cache V4 pool params (tick, hook) so buy_token/sell_token
                    # can use the real values instead of hardcoded defaults
                    if "tick" in mapped or "hook" in mapped:
                        self._v4_pool_params_cache[token_cs] = {
                            "tick": mapped.get("tick", 200),
                            "hook": mapped.get("hook", PONS_V2_HOOK),
                        }
                    logger.info(f"⚡ DexScreener fast-route: {mapped['venue']} | {mapped['quote']} | {mapped['target']}")
                    return mapped["venue"], mapped["target"], mapped["quote"], mapped.get("fee", 0)
        except asyncio.TimeoutError:
            logger.debug(f"DexScreener fast-check timed out for {token_cs}, falling through to on-chain checks")
        except Exception as e:
            logger.debug(f"DexScreener fast-check failed: {e}")
        # ==============================================================

        # 1. Bonding Curve check (Direct O(1) method)
        curve_addr, pair_token, is_graduated = await self.resolve_token_curve(token_cs)
        if curve_addr and not is_graduated:
            if pair_token.lower() == self.usdg_address.lower():
                return "LAUNCHPAD_CURVE_USDG", curve_addr, self.usdg_address, 0
            return "LAUNCHPAD_CURVE_ETH", curve_addr, ZERO, 0

        # 2. Parallel V3 WETH & V3 USDG Liquidity Probes
        async def check_v3_pool(quote_asset: str, fee: int, tag: str):
            try:
                pool_addr = await asyncio.to_thread(self.v3_factory.functions.getPool(quote_asset, token_cs, fee).call)
                if pool_addr and pool_addr != ZERO:
                    pool_contract = self.w3.eth.contract(address=pool_addr, abi=[
                        {"inputs":[],"name":"liquidity","outputs":[{"type":"uint128"}],"stateMutability":"view","type":"function"},
                        {"inputs":[],"name":"slot0","outputs":[{"name":"sqrtPriceX96","type":"uint160"},{"name":"tick","type":"int24"}],"stateMutability":"view","type":"function"}
                    ])
                    liq = await asyncio.to_thread(pool_contract.functions.liquidity().call)
                    slot0 = await asyncio.to_thread(pool_contract.functions.slot0().call)
                    # sqrtPriceX96 == 0 means pool exists but was never initialized (swap will revert)
                    if liq > 0 and slot0[0] > 0:
                        return f"UNISWAP_V3_{tag}", pool_addr, quote_asset, fee
            except Exception:
                pass
            return None

        v3_tasks = []
        for fee in [3000, 10000, 500, 100]:
            v3_tasks.append(check_v3_pool(self.weth_address, fee, "WETH"))
            v3_tasks.append(check_v3_pool(self.usdg_address, fee, "USDG"))

        v3_results = await asyncio.gather(*v3_tasks)
        for res in v3_results:
            if res is not None:
                return res

        # 3. Check against stock tokens (V3 / V4 style pools)
        async def check_stock_pool(stock_addr: str, fee: int):
            try:
                pool_addr = await asyncio.to_thread(self.v3_factory.functions.getPool(stock_addr, token_cs, fee).call)
                if pool_addr and pool_addr != ZERO:
                    liq_contract = self.w3.eth.contract(address=pool_addr, abi=[{"inputs":[],"name":"liquidity","outputs":[{"type":"uint128"}],"stateMutability":"view","type":"function"}])
                    liq = await asyncio.to_thread(liq_contract.functions.liquidity().call)
                    if liq > 0:
                        return "STOCK_PAIR", pool_addr, stock_addr, fee
            except Exception:
                pass
            return None

        # Check the FULL stock list (was previously hardcoded to just 5 tickers,
        # silently missing PLTR/AMD/GOOGL/COIN/MSTR/META/AMZN/NFLX/MSFT/QQQ
        # pairs on this fast path and forcing them onto the much slower
        # StockV4Router.detect() fallback). Still fully parallelized via gather.
        stock_tasks = []
        for stock_addr in EXTENDED_STOCK_LIST:
            if stock_addr.lower() != token_cs.lower():
                for fee in [3000, 10000, 500]:
                    stock_tasks.append(check_stock_pool(stock_addr, fee))

        if stock_tasks:
            stock_results = await asyncio.gather(*stock_tasks)
            for res in stock_results:
                if res is not None:
                    return res

        # 4. Uniswap V2 Pair fallback (Parallel)
        async def check_v2_pair(quote_asset: str, tag: str):
            try:
                pair_addr = await asyncio.to_thread(self.v2_factory.functions.getPair(quote_asset, token_cs).call)
                if pair_addr and pair_addr != ZERO:
                    res_contract = self.w3.eth.contract(address=pair_addr, abi=[{"inputs":[],"name":"getReserves","outputs":[{"type":"uint112"},{"type":"uint112"},{"type":"uint32"}],"stateMutability":"view","type":"function"}])
                    res = await asyncio.to_thread(res_contract.functions.getReserves().call)
                    if res[0] > 0 and res[1] > 0:
                        return f"UNISWAP_V2_{tag}", UNISWAP_V2_ROUTER, quote_asset, 0
            except Exception:
                pass
            return None

        v2_results = await asyncio.gather(
            check_v2_pair(self.weth_address, "WETH"),
            check_v2_pair(self.usdg_address, "USDG")
        )
        for res in v2_results:
            if res is not None:
                return res

        return "NONE", ZERO, self.weth_address, 0

    async def detect_venue_fast(self, token: str) -> dict:
        """Helper alias returning dict format"""
        venue, target, quote, fee = await self.detect_venue_and_route(token)
        return {
            "venue": venue,
            "target": target,
            "quote": quote,
            "fee": fee
        }

    async def force_buy_v4_or_stock(self, token: str, amount_eth: float, slippage_pct: float = 15.0,
                                    fee: int = 3000, tick: int = 60, hook: str = "0x" + "0"*40) -> Tuple[str, float]:
        """
        Aggressive forced buy for V4 / Stock-paired tokens - NO SIMULATION.
        Builds multi-hop / V4 swap via Universal Router and broadcasts directly.
        """
        token = self.w3.to_checksum_address(token)
        amount_wei = self.w3.to_wei(amount_eth, "ether")
        recipient = self.chain.account.address if self.chain.account else ZERO
        min_out = 1

        print(f"⚡ FORCED BUY (No Sim) for {token}")
        logger.info(f"⚡ FORCED BUY (No Sim) for {token} with {amount_eth} ETH")

        if getattr(self.config, "DRY_RUN", True):
            fake_hash = f"DRY_RUN_0x{int(time.time())}"
            logger.info(f"[DRY RUN] Forced V4/Stock buy simulated: {fake_hash}")
            return fake_hash, amount_eth * 1000.0

        WRAP_ETH = 0x0b
        V4_SWAP  = 0x10
        commands = bytes([WRAP_ETH, V4_SWAP])

        wrap_input = eth_abi.encode(['address', 'uint256'], [self.uni_router_address, amount_wei])
        v4_swap_input = make_v4_swap_input(
            token_in=self.weth_address,
            token_out=token,
            amount_in=amount_wei,
            min_out=min_out,
            recipient=recipient,
            fee=fee,
            tick_spacing=tick,
            hook_addr=hook
        )
        inputs = [wrap_input, v4_swap_input]
        deadline = int(time.time()) + 300

        calldata = self.uni_router.functions.execute(commands, inputs, deadline)._encode_transaction_data()

        latest = await asyncio.to_thread(self.w3.eth.get_block, 'latest')
        base_fee = latest.get('baseFeePerGas', self.w3.eth.gas_price)
        max_priority = max(int(base_fee * 0.1), 1_000_000)
        max_fee = int(base_fee * 1.35) + max_priority

        tx = {
            "from": recipient,
            "to": self.uni_router_address,
            "value": amount_wei,
            "data": calldata,
            "gas": 450000,
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": max_priority,
            "nonce": await self.chain.get_nonce(),
            "chainId": 4663
        }

        signed = self.chain.account.sign_transaction(tx)
        raw_tx_bytes = getattr(signed, 'raw_transaction', getattr(signed, 'rawTransaction', None))
        tx_hash_bytes = await asyncio.to_thread(self.w3.eth.send_raw_transaction, raw_tx_bytes)
        tx_hash = self.w3.to_hex(tx_hash_bytes)
        logger.info(f"⚡ Forced V4/Stock Buy Tx broadcasted: {tx_hash}")
        print(f"⚡ Forced V4/Stock Buy Tx: {tx_hash}")

        receipt = await self.chain.wait_for_receipt(tx_hash, timeout=45)
        status = receipt.get("status", 0)
        if status == 1:
            logger.info(f"⚡ Forced Buy confirmed in block {receipt.get('blockNumber')}")
            return tx_hash, 1.0
        else:
            logger.error(f"⚡ Forced Buy reverted: {tx_hash}")
            return tx_hash, 0.0

    # ─── Simulation Step (eth_call / eth_estimateGas) ───────────────────

    async def simulate_execution(self, tx: Dict[str, Any], venue: str, target: str, commands_bytes: str) -> Tuple[bool, str]:
        await self.verify_chain_id()
        try:
            gas_est = await asyncio.to_thread(self.w3.eth.estimate_gas, tx)
            msg = f"SIMULATION OK | Venue: {venue} | To: {target} | gas: {gas_est}"
            logger.info(msg)
            print(f"🎉🎉🎉 {msg}")
            return True, f"gas: {gas_est}"
        except Exception as e:
            revert_reason = str(e)
            msg = f"SIMULATION REVERT | Venue: {venue} | To: {target} | Revert: {revert_reason}"
            logger.warning(msg)
            print(f"❌ {msg}")
            return False, revert_reason

    # ─── Builders ────────────────────────────────────────────────────────

    def build_curve_buy_tx(self, curve_address: str, amount_in_wei: int, amount_out_min: int, recipient: str, pair_token: str) -> Tuple[Dict[str, Any], str]:
        """
        Pons curve function: buy(uint256 quoteIn, uint256 minTokensOut, address recipient)
        Signature selector: 0x2a3e87ea = buy(uint256,uint256,address)
        Native quote (pairToken == 0x0): msg.value == quoteIn
        USDG quote: msg.value == 0
        """
        buy_sel = self.w3.keccak(text='buy(uint256,uint256,address)')[:4].hex()
        calldata = buy_sel + eth_abi.encode(['uint256', 'uint256', 'address'], [amount_in_wei, amount_out_min, recipient]).hex()

        is_native = (pair_token == "0x" + "0"*40)
        tx = {
            'from': recipient,
            'to': self.w3.to_checksum_address(curve_address),
            'value': amount_in_wei if is_native else 0,
            'data': calldata,
            'chainId': 4663
        }
        return tx, "buy(uint256,uint256,address)"

    def build_v3_swap_tx(self, token_address: str, amount_in_wei: int, amount_out_min: int, recipient: str, quote_asset: str, fee: int) -> Tuple[Dict[str, Any], str]:
        """
        Builds SwapRouter02 transaction for V3 pools:
        - Single-hop exactInputSingle if quote_asset == WETH
        - Multi-hop exactInput if quote_asset == USDG (WETH -> USDG -> Token)
        """
        if quote_asset.lower() == self.usdg_address.lower():
            path_bytes = (
                bytes.fromhex(self.weth_address[2:]) +
                (500).to_bytes(3, 'big') +
                bytes.fromhex(self.usdg_address[2:]) +
                fee.to_bytes(3, 'big') +
                bytes.fromhex(self.w3.to_checksum_address(token_address)[2:])
            )
            calldata = self.router02.functions.exactInput((path_bytes, recipient, amount_in_wei, amount_out_min))._encode_transaction_data()
            tx = {
                'from': recipient,
                'to': self.swap_router02_addr,
                'value': amount_in_wei,
                'data': calldata,
                'chainId': 4663
            }
            return tx, "exactInput"
        else:
            params = (self.weth_address, self.w3.to_checksum_address(token_address), fee, recipient, amount_in_wei, amount_out_min, 0)
            calldata = self.router02.functions.exactInputSingle(params)._encode_transaction_data()
            tx = {
                'from': recipient,
                'to': self.swap_router02_addr,
                'value': amount_in_wei,
                'data': calldata,
                'chainId': 4663
            }
            return tx, "exactInputSingle"

    def build_v4_swap_tx(self, token_address: str, amount_in_wei: int, amount_out_min: int, recipient: str, quote_asset: str, fee: int = 3000, tick: int = 60, hook: str = "0x" + "0"*40) -> Tuple[Dict[str, Any], str]:
        """
        Single-hop V4 swap WETH -> Token.
        """
        v4_swap_input = make_v4_swap_input(self.weth_address, token_address, amount_in_wei, amount_out_min, recipient, fee=fee, tick_spacing=tick, hook_addr=hook)
        WRAP_ETH = 0x0b
        V4_SWAP  = 0x10
        commands = bytes([WRAP_ETH, V4_SWAP])

        wrap_input = eth_abi.encode(['address', 'uint256'], [self.uni_router_address, amount_in_wei])
        deadline   = int(time.time()) + 300

        calldata = self.uni_router.functions.execute(commands, [wrap_input, v4_swap_input], deadline)._encode_transaction_data()

        tx = {
            'from': recipient,
            'to': self.uni_router_address,
            'value': amount_in_wei,
            'data': calldata,
            'chainId': 4663
        }
        return tx, commands.hex()

    def build_v4_usdg_2hop_tx(self, token_address: str, eth_amount_wei: int, amount_out_min: int, recipient: str,
                              fee2: int = 3000, tick2: int = 60, hook2: str = PONS_V2_HOOK) -> Tuple[Dict[str, Any], str]:
        """
        Multi-hop V4 swap in a SINGLE V4_SWAP command:
        WRAP_ETH (0x0b) + V4_SWAP (0x10):
          Action 0x06: WETH -> USDG (amt_in = eth_amount_wei, min_out = 0)
          Action 0x06: USDG -> Token (amt_in = 0 [OPEN_DELTA], min_out = amount_out_min)
          Action 0x0c: SETTLE_ALL (WETH, eth_amount_wei)
          Action 0x0f: TAKE_ALL (Token, amount_out_min)
        """
        commands = bytes([0x0b, 0x10])  # WRAP_ETH + single V4_SWAP command

        wrap_input = eth_abi.encode(['address', 'uint256'], [self.uni_router_address, eth_amount_wei])

        weth_cs = self.weth_address
        usdg_cs = self.usdg_address
        tok_cs = self.w3.to_checksum_address(token_address)

        # Hop 1: WETH -> USDG (fee 500, tick 10, hook ZERO)
        if int(weth_cs, 16) < int(usdg_cs, 16):
            c0_1, c1_1 = weth_cs, usdg_cs
            z4o_1 = True
        else:
            c0_1, c1_1 = usdg_cs, weth_cs
            z4o_1 = False

        pool_key1 = (c0_1, c1_1, 500, 10, self.w3.to_checksum_address(ZERO))
        param_hop1 = eth_abi.encode(
            ['(address,address,uint24,int24,address)', 'bool', 'uint128', 'uint128', 'uint160', 'uint256', 'bytes'],
            [pool_key1, z4o_1, eth_amount_wei, 0, 0, 0, b'']
        )

        # Hop 2: USDG -> Token (fee2, tick2, hook2)
        # amt_in = 0 (OPEN_DELTA: consumes intermediate USDG delta from hop 1)
        if int(usdg_cs, 16) < int(tok_cs, 16):
            c0_2, c1_2 = usdg_cs, tok_cs
            z4o_2 = True
        else:
            c0_2, c1_2 = tok_cs, usdg_cs
            z4o_2 = False

        pool_key2 = (c0_2, c1_2, int(fee2), int(tick2), self.w3.to_checksum_address(hook2))
        param_hop2 = eth_abi.encode(
            ['(address,address,uint24,int24,address)', 'bool', 'uint128', 'uint128', 'uint160', 'uint256', 'bytes'],
            [pool_key2, z4o_2, 0, amount_out_min, 0, 0, b'']
        )

        # Action 0x0c: SETTLE_ALL (WETH)
        param_settle = eth_abi.encode(['address', 'uint256'], [weth_cs, eth_amount_wei])
        # Action 0x0f: TAKE_ALL (Token)
        param_take = eth_abi.encode(['address', 'uint256'], [tok_cs, amount_out_min])

        actions = bytes([0x06, 0x06, 0x0c, 0x0f])
        v4_swap_input = eth_abi.encode(
            ['bytes', 'bytes[]'],
            [actions, [param_hop1, param_hop2, param_settle, param_take]]
        )

        inputs = [wrap_input, v4_swap_input]
        deadline = int(time.time()) + 300

        calldata = self.uni_router.functions.execute(commands, inputs, deadline)._encode_transaction_data()

        tx = {
            'from': recipient,
            'to': self.uni_router_address,
            'value': eth_amount_wei,
            'data': calldata,
            'chainId': 4663
        }
        return tx, commands.hex()

    def build_v4_sell_tx(self, token_address: str, amount_in: int, min_out: int, recipient: str,
                         quote_asset: str, fee: int = 3000, tick: int = 60, hook: str = "0x" + "0"*40) -> Tuple[Dict[str, Any], str]:
        """
        Builds a V4 sell transaction via Universal Router.
        Pulls token with PERMIT2 (0x02), swaps via V4_SWAP (0x10), and unwraps WETH to ETH (0x0c).
        Supports:
        1. Single-hop: Token -> WETH -> ETH
        2. Two-hop USDG: Token -> USDG -> WETH -> ETH
        """
        tok_cs = self.w3.to_checksum_address(token_address)
        weth_cs = self.weth_address
        usdg_cs = self.usdg_address

        pull_input = eth_abi.encode(
            ["address", "address", "uint160"],
            [tok_cs, self.uni_router_address, int(amount_in)]
        )
        unwrap_input = eth_abi.encode(
            ["address", "uint256"],
            [recipient, int(min_out)]
        )

        if quote_asset.lower() == usdg_cs.lower():
            # 2-hop V4: Token -> USDG -> WETH + UNWRAP_WETH
            if int(tok_cs, 16) < int(usdg_cs, 16):
                c0_1, c1_1 = tok_cs, usdg_cs
                z4o_1 = True
            else:
                c0_1, c1_1 = usdg_cs, tok_cs
                z4o_1 = False
            pk1 = (c0_1, c1_1, int(fee), int(tick), self.w3.to_checksum_address(hook))
            p_hop1 = eth_abi.encode(
                ['(address,address,uint24,int24,address)', 'bool', 'uint128', 'uint128', 'uint160', 'uint256', 'bytes'],
                [pk1, z4o_1, int(amount_in), 0, 0, 0, b'']
            )

            # Hop 2: USDG -> WETH (fee 500, tick 10, hook ZERO)
            if int(usdg_cs, 16) < int(weth_cs, 16):
                c0_2, c1_2 = usdg_cs, weth_cs
                z4o_2 = True
            else:
                c0_2, c1_2 = weth_cs, usdg_cs
                z4o_2 = False
            pk2 = (c0_2, c1_2, 500, 10, self.w3.to_checksum_address(ZERO))
            p_hop2 = eth_abi.encode(
                ['(address,address,uint24,int24,address)', 'bool', 'uint128', 'uint128', 'uint160', 'uint256', 'bytes'],
                [pk2, z4o_2, 0, int(min_out), 0, 0, b'']
            )

            p_settle = eth_abi.encode(['address', 'uint256'], [tok_cs, int(amount_in)])
            p_take = eth_abi.encode(['address', 'uint256'], [weth_cs, int(min_out)])

            actions = bytes([0x06, 0x06, 0x0c, 0x0f])
            v4_input = eth_abi.encode(['bytes', 'bytes[]'], [actions, [p_hop1, p_hop2, p_settle, p_take]])

            commands = bytes([0x02, 0x10, 0x0c])  # PERMIT2_TRANSFER_FROM + V4_SWAP + UNWRAP_WETH
            inputs = [pull_input, v4_input, unwrap_input]
        else:
            # Single-hop V4: Token -> WETH + UNWRAP_WETH
            if int(tok_cs, 16) < int(weth_cs, 16):
                c0, c1 = tok_cs, weth_cs
                z4o = True
            else:
                c0, c1 = weth_cs, tok_cs
                z4o = False
            pk = (c0, c1, int(fee), int(tick), self.w3.to_checksum_address(hook))
            p_hop = eth_abi.encode(
                ['(address,address,uint24,int24,address)', 'bool', 'uint128', 'uint128', 'uint160', 'uint256', 'bytes'],
                [pk, z4o, int(amount_in), int(min_out), 0, 0, b'']
            )
            p_settle = eth_abi.encode(['address', 'uint256'], [tok_cs, int(amount_in)])
            p_take = eth_abi.encode(['address', 'uint256'], [weth_cs, int(min_out)])

            actions = bytes([0x06, 0x0c, 0x0f])
            v4_input = eth_abi.encode(['bytes', 'bytes[]'], [actions, [p_hop, p_settle, p_take]])

            commands = bytes([0x02, 0x10, 0x0c])  # PERMIT2_TRANSFER_FROM + V4_SWAP + UNWRAP_WETH
            inputs = [pull_input, v4_input, unwrap_input]

        deadline = int(time.time()) + 300
        calldata = self.uni_router.functions.execute(commands, inputs, deadline)._encode_transaction_data()
        tx = {
            'from': recipient,
            'to': self.uni_router_address,
            'value': 0,
            'data': calldata,
            'chainId': 4663
        }
        return tx, commands.hex()

    # ─── Public Buy / Sell ────────────────────────────────────────────────

    async def buy_token(self, token_address: str, eth_amount: float, slippage_pct: float, start_time: Optional[float] = None) -> Tuple[str, float]:
        if start_time is None:
            start_time = time.time()

        await self.verify_chain_id()
        token_address = self.w3.to_checksum_address(token_address)
        eth_wei = self.w3.to_wei(eth_amount, "ether")
        recipient = self.chain.account.address if self.chain.account else "0x" + "0"*40

        # Step 1: Detect venue and route per decision tree
        venue, target_addr, quote_asset, fee = await self.detect_venue_and_route(token_address)
        t_detect = time.time()
        logger.info(f"🔎 Token: {token_address} | Venue: {venue} | Target: {target_addr} | QuoteAsset: {quote_asset} | Fee: {fee} | Detection time: {t_detect - start_time:.2f}s")
        print(f"🔎 Token: {token_address} | Venue: {venue} | Target: {target_addr} | QuoteAsset: {quote_asset} | Fee: {fee}")

        if venue == "NONE":
            # Check Stock / V4 Router fallback
            info = await asyncio.to_thread(self.stock_v4.detect, token_address)
            if info.get("venue") != "NONE":
                venue = info["venue"]
                quote_asset = info.get("quote", ZERO)
                target_addr = info.get("target", ZERO)
                fee = info.get("fee", 0)
                if "tick" in info or "hook" in info:
                    self._v4_pool_params_cache[token_address] = {
                        "tick": info.get("tick", 200),
                        "hook": info.get("hook", PONS_V2_HOOK),
                    }
                logger.info(f"⚡ StockV4Router detected: {venue} | Target: {target_addr} | Quote: {quote_asset}")
                print(f"⚡ StockV4Router detected: {venue} | Target: {target_addr} | Quote: {quote_asset}")

                if getattr(self.config, "DRY_RUN", True):
                    ms = int((time.time() - start_time) * 1000)
                    log_line = f"{ms}ms | {token_address} | {venue} | {target_addr} | sent=False (DRY_RUN) | tx=DRY_RUN_0x{int(time.time())} | status=1 | token_delta=+{eth_amount*1000:,.4f} | quote_delta=-{eth_amount:.6f}"
                    logger.info(log_line)
                    print(log_line)
                    return f"DRY_RUN_0x{int(time.time())}", eth_amount * 1000.0

                bal_before = await self.chain.get_token_balance(token_address)
                tx_hash = None
                try:
                    tx_res = await asyncio.to_thread(self.stock_v4.buy, token_address, eth_amount)
                    tx_hash = tx_res[1] if isinstance(tx_res, tuple) else tx_res
                except Exception as e:
                    logger.warning(f"stock_v4 skip {token_address} {e}")
                    tx_hash = None

                # If stock_v4.buy returned None and it's a V4 ERC20-quoted token, invoke buy_stock_two_tx directly
                if not tx_hash and venue == "UNISWAP_V4" and quote_asset.lower() not in (self.weth_address.lower(), ZERO.lower(), "0x0000000000000000000000000000000000000000"):
                    try:
                        v4_tick = info.get("tick", 200)
                        v4_hook = info.get("hook", PONS_V2_HOOK)
                        res = await asyncio.to_thread(
                            self.stock_v4.buy_stock_two_tx,
                            token_address, quote_asset, eth_amount,
                            fee if fee else 0, v4_tick, v4_hook
                        )
                        tx_hash = res[1] if isinstance(res, tuple) else res
                    except Exception as e:
                        logger.error(f"Fallback buy_stock_two_tx failed for {token_address}: {e}")

                if tx_hash:
                    receipt = await self.chain.wait_for_receipt(tx_hash)
                    bal_after = await self.chain.get_token_balance(token_address)
                    tokens_received = bal_after - bal_before
                    status = receipt.get("status", 0)
                    ms = int((time.time() - start_time) * 1000)
                    log_line = f"{ms}ms | {token_address} | {venue} | {target_addr} | sent=True | tx={tx_hash} | status={status} | token_delta={tokens_received:+,.4f} | quote_delta=-{eth_amount:.6f}"
                    logger.info(log_line)
                    print(log_line)
                    if status == 1 and tokens_received > 0:
                        return tx_hash, tokens_received
                    return tx_hash, 0.0
                else:
                    logger.error(f"❌ StockV4Router.buy returned None for {token_address}")
                    return "", 0.0
            else:
                ms = int((time.time() - start_time) * 1000)
                log_line = f"{ms}ms | {token_address} | NONE | 0x0000000000000000000000000000000000000000 | sent=False | tx=None | status=None | token_delta=+0.0000 | quote_delta=+0.000000"
                logger.info(log_line)
                print(log_line)
                return "", 0.0

        min_out = 1

        if getattr(self.config, "DRY_RUN", True):
            ms = int((time.time() - start_time) * 1000)
            log_line = f"{ms}ms | {token_address} | {venue} | {target_addr} | sent=False (DRY_RUN) | tx=DRY_RUN_0x{int(time.time())} | status=1 | token_delta=+{eth_amount*1000:,.4f} | quote_delta=-{eth_amount:.6f}"
            logger.info(log_line)
            print(log_line)
            return f"DRY_RUN_0x{int(time.time())}", eth_amount * 1000.0

        if venue in ["V4", "STOCK_PAIR", "V4_STOCK"]:
            cached_params = self._v4_pool_params_cache.get(token_address, {})
            v4_tick = cached_params.get("tick", 60)
            v4_hook = cached_params.get("hook", "0x" + "0"*40)
            return await self.force_buy_v4_or_stock(
                token_address, eth_amount, slippage_pct,
                fee=fee, tick=v4_tick, hook=v4_hook
            )

        candidate_txs = []

        # Handle UNISWAP_V4 from stock_v4 fallback (includes USDG & stock quotes)
        if venue == "UNISWAP_V4":
            cached_params = self._v4_pool_params_cache.get(token_address, {})
            default_tick = 200 if quote_asset.lower() != self.weth_address.lower() else 60
            default_hook = PONS_V2_HOOK if quote_asset.lower() != self.weth_address.lower() else ("0x" + "0"*40)
            v4_tick = cached_params.get("tick", default_tick)
            v4_hook = cached_params.get("hook", default_hook)

            if quote_asset.lower() == self.usdg_address.lower():
                # Use detected fee/tick/hook for the second hop if available
                tx, cmd = self.build_v4_usdg_2hop_tx(
                    token_address, eth_wei, min_out, recipient,
                    fee2=fee if fee else 3000,
                    tick2=v4_tick,
                    hook2=v4_hook
                )
                candidate_txs.append((venue, self.uni_router_address, tx, cmd))
            elif self.w3.to_checksum_address(quote_asset) in EXTENDED_STOCK_LIST or quote_asset.lower() not in (self.weth_address.lower(), ZERO.lower(), "0x0000000000000000000000000000000000000000"):
                if getattr(self.config, "DRY_RUN", True):
                    return f"DRY_RUN_0x{int(time.time())}", eth_amount * 1000.0
                tick = v4_tick
                hook = v4_hook
                bal_before = await self.chain.get_token_balance(token_address)
                tx2 = None
                last_err = None
                # Two-leg buy (ETH->STOCK, then STOCK->TOKEN) has more failure
                # surface than a single-hop swap - a transient revert on either
                # leg (slippage on the stock leg, a stale nonce, etc.) used to
                # kill the whole trade with no retry. Give it one retry before
                # giving up.
                for attempt in range(2):
                    try:
                        tx1, tx2 = await asyncio.to_thread(
                            self.stock_v4.buy_stock_two_tx,
                            token_address, quote_asset, eth_amount,
                            fee if fee else 0,
                            tick,
                            hook
                        )
                        break
                    except Exception as e:
                        last_err = e
                        logger.warning(f"Stock two-tx buy attempt {attempt + 1}/2 failed for {token_address}: {e}")
                        if attempt == 0:
                            await asyncio.sleep(1)
                if tx2 is None:
                    logger.error(f"Stock two-tx buy failed for {token_address} after retry: {last_err}")
                    return "", 0.0
                # tx2 is the actual STOCK->TOKEN leg - that's the trade that
                # matters for position tracking. Confirm it and measure the
                # real tokens received instead of assuming a fixed amount.
                try:
                    await self.chain.wait_for_receipt(tx2)
                except Exception as e:
                    logger.warning(f"Could not confirm stock-leg buy receipt for {token_address}: {e}")
                bal_after = await self.chain.get_token_balance(token_address)
                tokens_received = bal_after - bal_before
                return tx2, tokens_received if tokens_received > 0 else 0.0
            else:
                tx_v4, cmd_v4 = self.build_v4_swap_tx(
                    token_address, eth_wei, min_out, recipient, quote_asset, fee=fee, tick=v4_tick, hook=v4_hook
                )
                candidate_txs.append((venue, self.uni_router_address, tx_v4, cmd_v4))

        elif venue in ["LAUNCHPAD_CURVE_ETH", "LAUNCHPAD_CURVE_USDG"]:
            # If pair is USDG, ensure USDG is approved to curve contract first and msg.value = 0
            if quote_asset.lower() == self.usdg_address.lower():
                eth_price_usd = await self.chain.get_eth_price_usd()
                quote_in_usdg = int(eth_amount * eth_price_usd * 10**6)
                try:
                    usdg_contract = self.w3.eth.contract(address=self.usdg_address, abi=ERC20_ABI)
                    usdg_bal = await self.chain._retry(usdg_contract.functions.balanceOf(recipient).call)
                    if usdg_bal < quote_in_usdg:
                        logger.warning(f"Insufficient USDG balance ({usdg_bal/1e6:.2f} USDG < {quote_in_usdg/1e6:.2f} USDG) to buy USDG curve. Skipping.")
                        return "", 0.0

                    allowance = await self.chain._retry(usdg_contract.functions.allowance(recipient, target_addr).call)
                    if allowance < quote_in_usdg:
                        logger.info(f"Approving USDG Curve {target_addr} for USDG spending...")
                        await self.chain.approve_token(self.usdg_address, target_addr, 2**256 - 1)
                except Exception as e:
                    logger.warning(f"USDG approval/balance check to curve {target_addr} failed: {e}")

                tx_c, cmd_c = self.build_curve_buy_tx(target_addr, quote_in_usdg, min_out, recipient, quote_asset)
                candidate_txs.append((venue, target_addr, tx_c, cmd_c))
            else:
                tx_c, cmd_c = self.build_curve_buy_tx(target_addr, eth_wei, min_out, recipient, quote_asset)
                candidate_txs.append((venue, target_addr, tx_c, cmd_c))

        elif "UNISWAP_V3" in venue:
            tx_v3, cmd_v3 = self.build_v3_swap_tx(token_address, eth_wei, min_out, recipient, quote_asset, fee=fee)
            candidate_txs.append((venue, self.swap_router02_addr, tx_v3, cmd_v3))

        elif "UNISWAP_V2" in venue:
            calldata = self.v2_router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
                min_out, [self.weth_address, token_address], recipient, int(time.time()) + 300
            )._encode_transaction_data()
            tx_v2 = {'from': recipient, 'to': UNISWAP_V2_ROUTER, 'value': eth_wei, 'data': calldata, 'chainId': 4663}
            candidate_txs.append((venue, UNISWAP_V2_ROUTER, tx_v2, "swapExactETHForTokens"))

        # Step 2: Check per-venue simulation setting (Kill-Switch Enabled)
        gas_limits = {
            "LAUNCHPAD_CURVE_ETH": 130000,
            "LAUNCHPAD_CURVE_USDG": 160000,
            "UNISWAP_V3_WETH": 260000,
            "UNISWAP_V3_USDG": 300000,
            "UNISWAP_V2_WETH": 200000,
            "UNISWAP_V2_USDG": 250000
        }

        for v_name, target, tx, cmd_str in candidate_txs:
            latest = await asyncio.to_thread(self.w3.eth.get_block, 'latest')
            base_fee = latest.get('baseFeePerGas', self.w3.eth.gas_price)
            tx['maxFeePerGas'] = int(base_fee * 1.25)
            tx['maxPriorityFeePerGas'] = max(int(base_fee * 0.1), 1_000_000)
            tx['gas'] = gas_limits.get(v_name, 350000)

            skip_sim = (v_name in self.no_sim_venues)

            if not skip_sim:
                t_sim_start = time.time()
                success, sim_result = await self.simulate_execution(tx, v_name, target, cmd_str)
                t_sim_end = time.time()
                if not success:
                    ms = int((time.time() - start_time) * 1000)
                    log_line = f"{ms}ms | {token_address} | {v_name} | {target} | sent=False | tx=None | status=SIM_FAIL | token_delta=+0.0000 | quote_delta=+0.000000"
                    logger.warning(log_line)
                    print(log_line)
                    continue
                logger.info(f"🚀 Simulation PASSED in {t_sim_end - t_sim_start:.2f}s for {v_name}")
            else:
                logger.info(f"⚡ NO-SIM FAST BROADCAST for {v_name} (proven venue)")

            # Query balance BEFORE transaction to ensure clean delta check
            bal_before = await self.chain.get_token_balance(token_address)

            tx_hash = await self.chain.send_transaction(tx)
            receipt = await self.chain.wait_for_receipt(tx_hash)

            # Query balance AFTER transaction receipt
            bal_after = await self.chain.get_token_balance(token_address)
            tokens_received = bal_after - bal_before
            status = receipt.get("status", 0)

            ms = int((time.time() - start_time) * 1000)
            quote_spent = -(eth_amount if quote_asset.lower() != self.usdg_address.lower() else (eth_wei / 1e6))
            log_line = f"{ms}ms | {token_address} | {v_name} | {target} | sent=True | tx={tx_hash} | status={status} | token_delta={tokens_received:+,.4f} | quote_delta={quote_spent:+.6f}"
            logger.info(log_line)
            print(log_line)

            if status == 1 and tokens_received > 0:
                return tx_hash, tokens_received
            else:
                # KILL SWITCH: If transaction failed or 0 tokens received on a no-sim venue, re-enable sim
                if v_name in self.no_sim_venues:
                    self.no_sim_venues.discard(v_name)
                    logger.critical(f"🚨 KILL-SWITCH TRIGGERED on {v_name}! Status={status}, Delta={tokens_received}. Re-enabling pre-flight simulation for {v_name}.")
                    print(f"🚨 KILL-SWITCH TRIGGERED on {v_name}! Status={status}, Delta={tokens_received}. Re-enabling pre-flight simulation for {v_name}.")
                return tx_hash, 0.0

        # ==========================================
        # FALLBACK: Primary route sim failed — try StockV4Router + V4/V2
        # ==========================================
        logger.warning(f"Primary route failed for {token_address}, trying fallback detection...")
        try:
            info = await asyncio.to_thread(self.stock_v4.detect, token_address)
            if info.get("venue") != "NONE":
                fb_venue = info["venue"]
                fb_quote = info.get("quote", ZERO)
                fb_target = info.get("target", ZERO)
                fb_fee = info.get("fee", 0)
                cached_params = self._v4_pool_params_cache.get(token_address, {})
                fb_tick = info.get("tick") or cached_params.get("tick", 60)
                fb_hook = info.get("hook") or cached_params.get("hook", ZERO)
                logger.info(f"Fallback detected: {fb_venue} | Target: {fb_target} | Quote: {fb_quote}")

                if fb_venue == "UNISWAP_V4":
                    if fb_quote.lower() in (self.weth_address.lower(), ZERO.lower(), "0x0000000000000000000000000000000000000000"):
                        tx_hash, _ = await self.force_buy_v4_or_stock(
                            token_address, eth_amount, slippage_pct,
                            fee=fb_fee, tick=fb_tick, hook=fb_hook
                        )
                        if tx_hash:
                            return tx_hash, eth_amount * 1000.0
                    elif fb_quote.lower() == self.usdg_address.lower():
                        tx_fb, _ = self.build_v4_usdg_2hop_tx(
                            token_address, eth_wei, min_out, recipient,
                            fee2=fb_fee, tick2=fb_tick, hook2=fb_hook
                        )
                        try:
                            gas_est = await asyncio.to_thread(self.w3.eth.estimate_gas, tx_fb)
                            tx_fb['gas'] = int(gas_est * 1.2)
                            tx_hash = await self.chain.send_transaction(tx_fb)
                            receipt = await self.chain.wait_for_receipt(tx_hash)
                            if receipt.get("status") == 1:
                                return tx_hash, eth_amount * 1000.0
                        except Exception as e:
                            logger.warning(f"Fallback V4 USDG sim failed: {e}")
                    else:
                        # Stock quote fallback
                        if getattr(self.config, "DRY_RUN", True):
                            return f"DRY_RUN_0x{int(time.time())}", eth_amount * 1000.0
                        fb_bal_before = await self.chain.get_token_balance(token_address)
                        try:
                            tx1, tx2 = await asyncio.to_thread(
                                self.stock_v4.buy_stock_two_tx,
                                token_address, fb_quote, eth_amount,
                                fb_fee, fb_tick, fb_hook
                            )
                            # tx2 is the STOCK->TOKEN leg that actually delivers
                            # the token - return that hash, and measure real
                            # tokens received instead of assuming a fixed amount.
                            try:
                                await self.chain.wait_for_receipt(tx2)
                            except Exception as e:
                                logger.warning(f"Could not confirm fallback stock-leg receipt for {token_address}: {e}")
                            fb_bal_after = await self.chain.get_token_balance(token_address)
                            fb_tokens_received = fb_bal_after - fb_bal_before
                            return tx2, fb_tokens_received if fb_tokens_received > 0 else 0.0
                        except Exception as e:
                            logger.warning(f"Stock two-tx fallback failed: {e}")

                elif fb_venue.startswith("UNISWAP_V2"):
                    calldata = self.v2_router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
                        min_out, [self.weth_address, token_address], recipient, int(time.time()) + 300
                    )._encode_transaction_data()
                    tx_v2 = {'from': recipient, 'to': UNISWAP_V2_ROUTER, 'value': eth_wei, 'data': calldata, 'chainId': 4663}
                    try:
                        gas_est = await asyncio.to_thread(self.w3.eth.estimate_gas, tx_v2)
                        tx_v2['gas'] = int(gas_est * 1.2)
                        tx_hash = await self.chain.send_transaction(tx_v2)
                        receipt = await self.chain.wait_for_receipt(tx_hash)
                        if receipt.get("status") == 1:
                            return tx_hash, eth_amount * 1000.0
                    except Exception as e:
                        logger.warning(f"Fallback V2 sim failed: {e}")
        except Exception as e:
            logger.warning(f"Fallback detection failed: {e}")

        # ==========================================
        # LAST RESORT: Aggressive no-sim V4 broadcast
        # ==========================================
        logger.warning(f"All simulated routes failed for {token_address}. Attempting no-sim V4 last resort...")
        try:
            tx_hash, _ = await self.force_buy_v4_or_stock(token_address, eth_amount, slippage_pct)
            if tx_hash:
                return tx_hash, eth_amount * 1000.0
        except Exception as e:
            logger.error(f"No-sim V4 last resort failed: {e}")

        logger.error(f"❌ All buy routes failed for {token_address}")
        return "", 0.0

    async def sell_token(self, token_address: str, token_amount: float, slippage_pct: float = 15.0) -> Tuple[str, float]:
        await self.verify_chain_id()
        token_address = self.w3.to_checksum_address(token_address)
        recipient = self.chain.account.address if self.chain.account else "0x" + "0"*40

        venue, target_addr, quote_asset, fee = await self.detect_venue_and_route(token_address)
        logger.info(f"Selling {token_amount} of {token_address} | Detected Venue: {venue}")
        print(f"Selling {token_amount} of {token_address}")
        print(f"Detected Venue: {venue}")

        if getattr(self.config, "DRY_RUN", True):
            logger.info(f"[DRY RUN] Would sell {token_amount} of {token_address} on venue {venue}")
            print(f"⚡ [DRY RUN] Would sell {token_amount} of {token_address} on venue {venue}")
            return f"DRY_RUN_SELL_0x{int(time.time())}", token_amount

        # Get decimals
        token_contract = self.w3.eth.contract(address=token_address, abi=ERC20_ABI)
        try:
            decimals = await self.chain._retry(token_contract.functions.decimals().call)
        except Exception:
            decimals = 18

        amount_in = int(token_amount * (10**decimals))
        min_out = 1

        if venue in ("UNISWAP_V4", "NONE"):
            # If WETH/Native quote, first try StockV4Router.sell()
            if quote_asset.lower() in (self.weth_address.lower(), ZERO.lower(), "0x0000000000000000000000000000000000000000"):
                try:
                    bal_before = await self.chain.get_token_balance(token_address)
                    tx = await asyncio.to_thread(self.stock_v4.sell, token_address, amount_in)
                    if tx:
                        receipt = await self.chain.wait_for_receipt(tx)
                        bal_after = await self.chain.get_token_balance(token_address)
                        tokens_sold = bal_before - bal_after
                        status = receipt.get("status", 0)
                        if status == 1 and tokens_sold > 0:
                            return tx, tokens_sold
                except Exception as e:
                    logger.warning(f"V4 stock_v4.sell failed: {e}, falling back to direct router sell")

            # Direct V4 Sell via Universal Router with Permit2
            try:
                await asyncio.to_thread(self.stock_v4.ensure_permit2, token_address, amount_in)
                cached_params = self._v4_pool_params_cache.get(token_address, {})
                default_tick = 200 if quote_asset.lower() != self.weth_address.lower() else 60
                default_hook = PONS_V2_HOOK if quote_asset.lower() != self.weth_address.lower() else ("0x" + "0"*40)
                v4_tick = cached_params.get("tick", default_tick)
                v4_hook = cached_params.get("hook", default_hook)
                v4_fee = fee if fee else 3000

                tx_v4, cmd_v4 = self.build_v4_sell_tx(
                    token_address, amount_in, min_out, recipient, quote_asset,
                    fee=v4_fee, tick=v4_tick, hook=v4_hook
                )
                tx = tx_v4
                spender = self.uni_router_address
                venue = "UNISWAP_V4"
            except Exception as e:
                logger.error(f"Failed to build V4 sell tx for {token_address}: {e}")
                return "", 0.0

        elif venue in ["LAUNCHPAD_CURVE_ETH", "LAUNCHPAD_CURVE_USDG"]:
            spender = target_addr
            allowance = await self.chain._retry(token_contract.functions.allowance(recipient, spender).call)
            if allowance < amount_in:
                logger.info(f"Approving {spender} to spend {token_address}...")
                await self.chain.approve_token(token_address, spender, 2**256 - 1)
            curve = self.w3.eth.contract(address=spender, abi=PONS_CURVE_ABI)
            calldata = curve.functions.sell(amount_in, min_out, recipient)._encode_transaction_data()
            tx = {'from': recipient, 'to': spender, 'value': 0, 'data': calldata, 'chainId': 4663}

        elif venue == "UNISWAP_V3_WETH":
            spender = self.swap_router02_addr
            allowance = await self.chain._retry(token_contract.functions.allowance(recipient, spender).call)
            if allowance < amount_in:
                logger.info(f"Approving {spender} to spend {token_address}...")
                await self.chain.approve_token(token_address, spender, 2**256 - 1)
            router = self.w3.eth.contract(address=self.swap_router02_addr, abi=SWAP_ROUTER02_ABI)
            params = (token_address, self.weth_address, fee if fee else 10000, recipient, amount_in, min_out, 0)
            calldata = router.functions.exactInputSingle(params)._encode_transaction_data()
            tx = {'from': recipient, 'to': self.swap_router02_addr, 'value': 0, 'data': calldata, 'chainId': 4663}

        elif venue == "UNISWAP_V3_USDG":
            spender = self.swap_router02_addr
            allowance = await self.chain._retry(token_contract.functions.allowance(recipient, spender).call)
            if allowance < amount_in:
                logger.info(f"Approving {spender} to spend {token_address}...")
                await self.chain.approve_token(token_address, spender, 2**256 - 1)
            router = self.w3.eth.contract(address=self.swap_router02_addr, abi=SWAP_ROUTER02_ABI)
            path_bytes = (
                bytes.fromhex(token_address[2:]) +
                (fee if fee else 3000).to_bytes(3, 'big') +
                bytes.fromhex(self.usdg_address[2:]) +
                (500).to_bytes(3, 'big') +
                bytes.fromhex(self.weth_address[2:])
            )
            calldata = router.functions.exactInput((path_bytes, recipient, amount_in, min_out))._encode_transaction_data()
            tx = {'from': recipient, 'to': self.swap_router02_addr, 'value': 0, 'data': calldata, 'chainId': 4663}

        elif venue in ("STOCK_PAIR", "UNISWAP_V3_STOCK"):
            spender = self.swap_router02_addr
            allowance = await self.chain._retry(token_contract.functions.allowance(recipient, spender).call)
            if allowance < amount_in:
                logger.info(f"Approving {spender} to spend {token_address}...")
                await self.chain.approve_token(token_address, spender, 2**256 - 1)
            router = self.w3.eth.contract(address=self.swap_router02_addr, abi=SWAP_ROUTER02_ABI)
            path_bytes = (
                bytes.fromhex(token_address[2:]) +
                (fee if fee else 3000).to_bytes(3, 'big') +
                bytes.fromhex(quote_asset[2:]) +
                (500).to_bytes(3, 'big') +
                bytes.fromhex(self.usdg_address[2:]) +
                (500).to_bytes(3, 'big') +
                bytes.fromhex(self.weth_address[2:])
            )
            calldata = router.functions.exactInput((path_bytes, recipient, amount_in, min_out))._encode_transaction_data()
            tx = {'from': recipient, 'to': self.swap_router02_addr, 'value': 0, 'data': calldata, 'chainId': 4663}

        elif venue == "UNISWAP_V2_WETH":
            spender = self.w3.to_checksum_address(UNISWAP_V2_ROUTER)
            allowance = await self.chain._retry(token_contract.functions.allowance(recipient, spender).call)
            if allowance < amount_in:
                logger.info(f"Approving {spender} to spend {token_address}...")
                await self.chain.approve_token(token_address, spender, 2**256 - 1)
            calldata = self.v2_router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
                amount_in, min_out, [token_address, self.weth_address], recipient, int(time.time()) + 300
            )._encode_transaction_data()
            tx = {'from': recipient, 'to': UNISWAP_V2_ROUTER, 'value': 0, 'data': calldata, 'chainId': 4663}

        elif venue == "UNISWAP_V2_USDG":
            spender = self.w3.to_checksum_address(UNISWAP_V2_ROUTER)
            allowance = await self.chain._retry(token_contract.functions.allowance(recipient, spender).call)
            if allowance < amount_in:
                logger.info(f"Approving {spender} to spend {token_address}...")
                await self.chain.approve_token(token_address, spender, 2**256 - 1)
            calldata = self.v2_router.functions.swapExactTokensForTokensSupportingFeeOnTransferTokens(
                amount_in, min_out, [token_address, self.usdg_address], recipient, int(time.time()) + 300
            )._encode_transaction_data()
            tx = {'from': recipient, 'to': UNISWAP_V2_ROUTER, 'value': 0, 'data': calldata, 'chainId': 4663}

        else:
            logger.error(f"No supported sell venue found for {token_address}")
            return "", 0.0

        # Broadcast
        gas_limits = {
            "LAUNCHPAD_CURVE_ETH": 120000,
            "LAUNCHPAD_CURVE_USDG": 140000,
            "UNISWAP_V3_WETH": 260000,
            "UNISWAP_V3_USDG": 300000,
            "UNISWAP_V3_STOCK": 360000,
            "STOCK_PAIR": 360000,
            "UNISWAP_V2_WETH": 220000,
            "UNISWAP_V2_USDG": 260000,
            "UNISWAP_V4": 450000,
        }

        latest = await asyncio.to_thread(self.w3.eth.get_block, 'latest')
        base_fee = latest.get('baseFeePerGas', self.w3.eth.gas_price)
        tx['maxFeePerGas'] = int(base_fee * 1.25)
        tx['maxPriorityFeePerGas'] = max(int(base_fee * 0.1), 1_000_000)
        tx['gas'] = gas_limits.get(venue, 350000)

        skip_sim = (venue in self.no_sim_venues)

        if not skip_sim:
            success, sim_result = await self.simulate_execution(tx, f"SELL_{venue}", tx['to'], "sell")
            if not success:
                logger.error(f"Sell simulation failed for {token_address}: {sim_result}")
                return "", 0.0
        else:
            logger.info(f"⚡ NO-SIM FAST BROADCAST for sell on {venue} (proven venue)")

        t_sell_start = time.time()
        bal_before = await self.chain.get_token_balance(token_address)
        tx_hash = await self.chain.send_transaction(tx)
        logger.info(f"✅ SELL submitted! Tx: {tx_hash}. Waiting for receipt...")
        receipt = await self.chain.wait_for_receipt(tx_hash)
        bal_after = await self.chain.get_token_balance(token_address)
        tokens_sold = bal_before - bal_after
        status = receipt.get("status", 0)

        ms = int((time.time() - t_sell_start) * 1000)
        log_line = f"{ms}ms | {token_address} | {venue} | {spender} | sent=True | tx={tx_hash} | status={status} | token_delta={-tokens_sold:+,.4f} | quote_delta=+0.000000"
        logger.info(log_line)
        print(log_line)

        if status == 1 and tokens_sold > 0:
            return tx_hash, tokens_sold
        else:
            if venue in self.no_sim_venues:
                self.no_sim_venues.discard(venue)
                logger.critical(f"🚨 KILL-SWITCH TRIGGERED on {venue} sell! Status={status}, Sold={tokens_sold}. Re-enabling simulation.")
                print(f"🚨 KILL-SWITCH TRIGGERED on {venue} sell! Status={status}, Sold={tokens_sold}. Re-enabling simulation.")
            return tx_hash, 0.0

    async def get_token_price_eth(self, token_address: str) -> float:
        """
        Calculates the current live DEX price of 1 token in ETH across all supported venues.
        Supports:
        - LAUNCHPAD_CURVE_ETH & LAUNCHPAD_CURVE_USDG
        - UNISWAP_V3_WETH & UNISWAP_V3_USDG
        - UNISWAP_V4 (Native, WETH, USDG, and Stock quote pools)
        - STOCK_PAIR & UNISWAP_V3_STOCK
        - UNISWAP_V2_WETH & UNISWAP_V2_USDG
        - Fallback: Non-blocking DexScreener lookup
        """
        await self.verify_chain_id()
        token_cs = self.w3.to_checksum_address(token_address)
        try:
            venue, target_addr, quote_asset, fee = await self.detect_venue_and_route(token_cs)

            if venue == "LAUNCHPAD_CURVE_ETH":
                res = await asyncio.to_thread(self.w3.eth.call, {'to': target_addr, 'data': '0x0902f1ac'})
                if res and len(res) >= 64:
                    r0 = int(res.hex()[:64], 16)
                    r1 = int(res.hex()[64:], 16)
                    if r1 > 0:
                        return (r0 / 1e18) / (r1 / 1e18)

            elif venue == "LAUNCHPAD_CURVE_USDG":
                res = await asyncio.to_thread(self.w3.eth.call, {'to': target_addr, 'data': '0x0902f1ac'})
                if res and len(res) >= 64:
                    r0 = int(res.hex()[:64], 16)
                    r1 = int(res.hex()[64:], 16)
                    if r1 > 0:
                        price_usdg = (r0 / 1e6) / (r1 / 1e18)
                        eth_price_usd = await self.chain.get_eth_price_usd()
                        return price_usdg / eth_price_usd if eth_price_usd > 0 else 0.0

            elif venue == "UNISWAP_V3_WETH":
                pool_contract = self.w3.eth.contract(address=target_addr, abi=[
                    {'inputs': [], 'name': 'slot0', 'outputs': [{'name': 'sqrtPriceX96', 'type': 'uint160'}, {'name': 'tick', 'type': 'int24'}], 'stateMutability': 'view', 'type': 'function'},
                    {'inputs': [], 'name': 'token0', 'outputs': [{'name': '', 'type': 'address'}], 'stateMutability': 'view', 'type': 'function'},
                    {'inputs': [], 'name': 'token1', 'outputs': [{'name': '', 'type': 'address'}], 'stateMutability': 'view', 'type': 'function'}
                ])
                s0 = await asyncio.to_thread(pool_contract.functions.slot0().call)
                t0 = await asyncio.to_thread(pool_contract.functions.token0().call)
                token_contract = self.w3.eth.contract(address=token_cs, abi=ERC20_ABI)
                try:
                    dec = await self.chain._retry(token_contract.functions.decimals().call)
                except Exception:
                    dec = 18

                sqrtPrice = s0[0]
                if sqrtPrice > 0:
                    raw_price = (sqrtPrice / (2**96)) ** 2
                    if t0.lower() == self.weth_address.lower():
                        price_in_eth = (1.0 / raw_price) * (10**dec / 1e18) if raw_price > 0 else 0.0
                    else:
                        price_in_eth = raw_price * (10**dec / 1e18)
                    return price_in_eth

            elif venue == "UNISWAP_V3_USDG":
                pool_contract = self.w3.eth.contract(address=target_addr, abi=[
                    {'inputs': [], 'name': 'slot0', 'outputs': [{'name': 'sqrtPriceX96', 'type': 'uint160'}, {'name': 'tick', 'type': 'int24'}], 'stateMutability': 'view', 'type': 'function'},
                    {'inputs': [], 'name': 'token0', 'outputs': [{'name': '', 'type': 'address'}], 'stateMutability': 'view', 'type': 'function'},
                    {'inputs': [], 'name': 'token1', 'outputs': [{'name': '', 'type': 'address'}], 'stateMutability': 'view', 'type': 'function'}
                ])
                s0 = await asyncio.to_thread(pool_contract.functions.slot0().call)
                t0 = await asyncio.to_thread(pool_contract.functions.token0().call)
                token_contract = self.w3.eth.contract(address=token_cs, abi=ERC20_ABI)
                try:
                    dec = await self.chain._retry(token_contract.functions.decimals().call)
                except Exception:
                    dec = 18

                sqrtPrice = s0[0]
                if sqrtPrice > 0:
                    raw_price = (sqrtPrice / (2**96)) ** 2
                    if t0.lower() == self.usdg_address.lower():
                        price_usdg = (1.0 / raw_price) * (10**dec / 1e6) if raw_price > 0 else 0.0
                    else:
                        price_usdg = raw_price * (10**dec / 1e6)
                    eth_price_usd = await self.chain.get_eth_price_usd()
                    return price_usdg / eth_price_usd if eth_price_usd > 0 else 0.0

            elif venue == "UNISWAP_V4":
                cached_params = self._v4_pool_params_cache.get(token_cs, {})
                fee_val = fee if fee else cached_params.get("fee", 0)
                tick_val = cached_params.get("tick", 200 if quote_asset.lower() != self.weth_address.lower() else 60)
                hook_val = cached_params.get("hook", PONS_V2_HOOK if quote_asset.lower() != self.weth_address.lower() else ZERO)
                q_cs = self.w3.to_checksum_address(quote_asset)

                if int(token_cs, 16) < int(q_cs, 16):
                    c0, c1 = token_cs, q_cs
                else:
                    c0, c1 = q_cs, token_cs

                pid = pool_id_from_key(c0, c1, fee_val, tick_val, hook_val)
                s0 = await asyncio.to_thread(self.state_view.functions.getSlot0(pid).call)
                sqrtPrice = s0[0]
                if sqrtPrice > 0:
                    raw_price = (sqrtPrice / (2**96)) ** 2
                    token_contract = self.w3.eth.contract(address=token_cs, abi=ERC20_ABI)
                    try:
                        dec = await self.chain._retry(token_contract.functions.decimals().call)
                    except Exception:
                        dec = 18

                    q_dec = 6 if q_cs.lower() == self.usdg_address.lower() else 18

                    if token_cs.lower() == c0.lower():
                        price_in_quote = raw_price * (10**dec) / (10**q_dec)
                    else:
                        price_in_quote = (1.0 / raw_price) * (10**dec) / (10**q_dec) if raw_price > 0 else 0.0

                    if q_cs.lower() in (self.weth_address.lower(), ZERO.lower(), "0x0000000000000000000000000000000000000000"):
                        return price_in_quote
                    elif q_cs.lower() == self.usdg_address.lower():
                        eth_price_usd = await self.chain.get_eth_price_usd()
                        return price_in_quote / eth_price_usd if eth_price_usd > 0 else 0.0
                    elif q_cs in EXTENDED_STOCK_LIST:
                        stock_pool = await asyncio.to_thread(self.v3_factory.functions.getPool(q_cs, self.usdg_address, 500).call)
                        if stock_pool and stock_pool != ZERO:
                            sp_contract = self.w3.eth.contract(address=stock_pool, abi=[
                                {'inputs': [], 'name': 'slot0', 'outputs': [{'name': 'sqrtPriceX96', 'type': 'uint160'}, {'name': 'tick', 'type': 'int24'}], 'stateMutability': 'view', 'type': 'function'},
                                {'inputs': [], 'name': 'token0', 'outputs': [{'name': '', 'type': 'address'}], 'stateMutability': 'view', 'type': 'function'}
                            ])
                            s0_sp = await asyncio.to_thread(sp_contract.functions.slot0().call)
                            t0_sp = await asyncio.to_thread(sp_contract.functions.token0().call)
                            if s0_sp[0] > 0:
                                sp_raw = (s0_sp[0] / (2**96)) ** 2
                                stock_usd = (sp_raw * 1e12) if t0_sp.lower() == q_cs.lower() else ((1.0 / sp_raw) * 1e12 if sp_raw > 0 else 0.0)
                                price_usd = price_in_quote * stock_usd
                                eth_price_usd = await self.chain.get_eth_price_usd()
                                return price_usd / eth_price_usd if eth_price_usd > 0 else 0.0

            elif venue in ("STOCK_PAIR", "UNISWAP_V3_STOCK"):
                pool_contract = self.w3.eth.contract(address=target_addr, abi=[
                    {'inputs': [], 'name': 'slot0', 'outputs': [{'name': 'sqrtPriceX96', 'type': 'uint160'}, {'name': 'tick', 'type': 'int24'}], 'stateMutability': 'view', 'type': 'function'},
                    {'inputs': [], 'name': 'token0', 'outputs': [{'name': '', 'type': 'address'}], 'stateMutability': 'view', 'type': 'function'},
                    {'inputs': [], 'name': 'token1', 'outputs': [{'name': '', 'type': 'address'}], 'stateMutability': 'view', 'type': 'function'}
                ])
                s0 = await asyncio.to_thread(pool_contract.functions.slot0().call)
                t0 = await asyncio.to_thread(pool_contract.functions.token0().call)
                token_contract = self.w3.eth.contract(address=token_cs, abi=ERC20_ABI)
                try:
                    dec = await self.chain._retry(token_contract.functions.decimals().call)
                except Exception:
                    dec = 18

                sqrtPrice = s0[0]
                if sqrtPrice > 0:
                    raw_price = (sqrtPrice / (2**96)) ** 2
                    if t0.lower() == quote_asset.lower():
                        price_in_stock = (1.0 / raw_price) * (10**dec / 1e18) if raw_price > 0 else 0.0
                    else:
                        price_in_stock = raw_price * (10**dec / 1e18)

                    stock_pool = await asyncio.to_thread(self.v3_factory.functions.getPool(quote_asset, self.usdg_address, 500).call)
                    if stock_pool and stock_pool != ZERO:
                        sp_contract = self.w3.eth.contract(address=stock_pool, abi=[
                            {'inputs': [], 'name': 'slot0', 'outputs': [{'name': 'sqrtPriceX96', 'type': 'uint160'}, {'name': 'tick', 'type': 'int24'}], 'stateMutability': 'view', 'type': 'function'},
                            {'inputs': [], 'name': 'token0', 'outputs': [{'name': '', 'type': 'address'}], 'stateMutability': 'view', 'type': 'function'}
                        ])
                        s0_sp = await asyncio.to_thread(sp_contract.functions.slot0().call)
                        t0_sp = await asyncio.to_thread(sp_contract.functions.token0().call)
                        if s0_sp[0] > 0:
                            sp_raw = (s0_sp[0] / (2**96)) ** 2
                            stock_usd = (sp_raw * 1e12) if t0_sp.lower() == quote_asset.lower() else ((1.0 / sp_raw) * 1e12 if sp_raw > 0 else 0.0)
                            price_usd = price_in_stock * stock_usd
                            eth_price_usd = await self.chain.get_eth_price_usd()
                            return price_usd / eth_price_usd if eth_price_usd > 0 else 0.0

            elif "UNISWAP_V2" in venue:
                pair_addr = await asyncio.to_thread(self.v2_factory.functions.getPair(token_cs, quote_asset).call)
                if pair_addr and pair_addr != ZERO:
                    pair_contract = self.w3.eth.contract(address=pair_addr, abi=[
                        {"inputs":[],"name":"getReserves","outputs":[{"type":"uint112"},{"type":"uint112"},{"type":"uint32"}],"stateMutability":"view","type":"function"},
                        {"inputs":[],"name":"token0","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}
                    ])
                    res = await asyncio.to_thread(pair_contract.functions.getReserves().call)
                    t0 = await asyncio.to_thread(pair_contract.functions.token0().call)
                    token_contract = self.w3.eth.contract(address=token_cs, abi=ERC20_ABI)
                    try:
                        dec = await self.chain._retry(token_contract.functions.decimals().call)
                    except Exception:
                        dec = 18
                    if t0.lower() == token_cs.lower():
                        r_token, r_quote = res[0], res[1]
                    else:
                        r_quote, r_token = res[0], res[1]
                    if r_token > 0:
                        if quote_asset.lower() == self.weth_address.lower():
                            return (r_quote / 1e18) / (r_token / (10**dec))
                        elif quote_asset.lower() == self.usdg_address.lower():
                            px_usdg = (r_quote / 1e6) / (r_token / (10**dec))
                            eth_price_usd = await self.chain.get_eth_price_usd()
                            return px_usdg / eth_price_usd if eth_price_usd > 0 else 0.0

        except Exception as e:
            logger.debug(f"Error fetching token price in ETH for {token_address}: {e}")

        px = await asyncio.to_thread(get_price_eth_dexscreener, token_address)
        if px > 0:
            return px

        return 0.0

    async def estimate_tokens_for_eth(self, token_address: str, eth_amount: float) -> float:
        """
        Estimates the number of tokens received for a given ETH amount.
        """
        price_eth = await self.get_token_price_eth(token_address)
        if price_eth > 0:
            return eth_amount / price_eth
        return 0.0


# ─── Standalone Forced Simulation Helpers ─────────────────────────────────

def force_simulate_usdg_curve(token_address: str, quote_amount_usdg: float = 1.0, w3=None, recipient=None):
    """Force test Ungraduated USDG Curve buy"""
    print("=" * 70)
    print(f"FORCED SIMULATION: Ungraduated USDG Curve for {token_address}")
    print("=" * 70)

    if w3 is None:
        w3 = Web3(Web3.HTTPProvider('https://rpc.mainnet.chain.robinhood.com'))
    if recipient is None:
        recipient = "0x801F3F2822Af33A5A127aeEc4487882464AB4C31"

    token = w3.to_checksum_address(token_address)
    usdg = w3.to_checksum_address(USDG_ADDRESS)
    recipient = w3.to_checksum_address(recipient)

    quote_in = int(quote_amount_usdg * 10**6)
    min_out = 1

    usdg_contract = w3.eth.contract(address=usdg, abi=ERC20_ABI)
    balance = usdg_contract.functions.balanceOf(recipient).call()
    print(f"USDG Balance: {balance / 10**6}")

    curve_contract_abi = [
        {"inputs": [{"name": "quoteIn", "type": "uint256"}, {"name": "minTokensOut", "type": "uint256"}, {"name": "recipient", "type": "address"}], "name": "buy", "outputs": [{"name": "tokensReceived", "type": "uint256"}], "stateMutability": "payable", "type": "function"}
    ]

    try:
        # Example or placeholder curve address
        curve_addr = "0x1DB4E3fE3f941e4c19Cf87488dC653D8E9D6Dae4"
        curve_contract = w3.eth.contract(address=w3.to_checksum_address(curve_addr), abi=curve_contract_abi)
        allowance = usdg_contract.functions.allowance(recipient, curve_addr).call()
        print(f"Current Allowance: {allowance / 10**6}")

        tx = curve_contract.functions.buy(
            quote_in,
            min_out,
            recipient
        ).build_transaction({
            "from": recipient,
            "value": 0,
            "gas": 300000,
            "nonce": w3.eth.get_transaction_count(recipient),
            "chainId": 4663
        })

        gas_estimate = w3.eth.estimate_gas(tx)
        print(f"SIMULATION OK | Venue: LAUNCHPAD_CURVE_USDG | To: {curve_addr} | gas: {gas_estimate}")
        return True

    except Exception as e:
        print(f"SIMULATION REVERT | Venue: LAUNCHPAD_CURVE_USDG")
        print(f"Revert reason: {e}")
        return False


def force_simulate_v4_weth(token_address: str, eth_amount: float = 0.0002, w3=None, recipient=None, fee: int = 3000, hook: str = "0x0000000000000000000000000000000000000000"):
    print("=" * 70)
    print(f"FORCED SIMULATION: Graduated V4 WETH for {token_address}")
    print("=" * 70)

    if w3 is None:
        w3 = Web3(Web3.HTTPProvider('https://rpc.mainnet.chain.robinhood.com'))
    if recipient is None:
        recipient = "0x801F3F2822Af33A5A127aeEc4487882464AB4C31"

    token = w3.to_checksum_address(token_address)
    amount_in = w3.to_wei(eth_amount, 'ether')
    recipient = w3.to_checksum_address(recipient)
    min_out = 1
    weth = w3.to_checksum_address(WETH_ADDRESS)
    router_addr = w3.to_checksum_address(UNIVERSAL_ROUTER_ADDR)

    try:
        commands = bytes([0x0b, 0x10])  # WRAP_ETH + V4_SWAP

        wrap_input = eth_abi.encode(
            ['address', 'uint256'],
            [router_addr, amount_in]
        )

        v4_input = make_v4_swap_input(
            token_in=weth,
            token_out=token,
            amount_in=amount_in,
            min_out=min_out,
            recipient=recipient,
            fee=fee,
            tick_spacing=60,
            hook_addr=hook
        )

        inputs = [wrap_input, v4_input]
        router = w3.eth.contract(address=router_addr, abi=UNIVERSAL_ROUTER_ABI)

        tx = router.functions.execute(
            commands,
            inputs,
            int(time.time()) + 600
        ).build_transaction({
            "from": recipient,
            "value": amount_in,
            "gas": 500000,
            "nonce": w3.eth.get_transaction_count(recipient),
            "chainId": 4663
        })

        gas_estimate = w3.eth.estimate_gas(tx)
        print(f"SIMULATION OK | Venue: UNISWAP_V4_WETH | gas: {gas_estimate}")
        return True

    except Exception as e:
        print(f"SIMULATION REVERT | Venue: UNISWAP_V4_WETH")
        print(f"Revert: {e}")
        return False


def force_simulate_v3_usdg(token_address: str, eth_amount: float = 0.0002, w3=None, recipient=None, fee1: int = 500, fee2: int = 3000):
    print("=" * 70)
    print(f"FORCED SIMULATION: Graduated V3 USDG for {token_address}")
    print("=" * 70)

    if w3 is None:
        w3 = Web3(Web3.HTTPProvider('https://rpc.mainnet.chain.robinhood.com'))
    if recipient is None:
        recipient = "0x801F3F2822Af33A5A127aeEc4487882464AB4C31"

    token = w3.to_checksum_address(token_address)
    amount_in = w3.to_wei(eth_amount, 'ether')
    recipient = w3.to_checksum_address(recipient)
    min_out = 1
    weth = w3.to_checksum_address(WETH_ADDRESS)
    usdg = w3.to_checksum_address(USDG_ADDRESS)
    router_addr = w3.to_checksum_address(UNIVERSAL_ROUTER_ADDR)

    try:
        # SwapRouter02 exactInput multi-hop (WETH -> USDG -> Token)
        router02_addr = w3.to_checksum_address(UNISWAP_V3_SWAPROUTER02)
        router02 = w3.eth.contract(address=router02_addr, abi=SWAP_ROUTER02_ABI)

        path_bytes = (
            bytes.fromhex(weth[2:]) +
            fee1.to_bytes(3, 'big') +
            bytes.fromhex(usdg[2:]) +
            fee2.to_bytes(3, 'big') +
            bytes.fromhex(token[2:])
        )

        calldata = router02.functions.exactInput((path_bytes, recipient, amount_in, min_out))._encode_transaction_data()
        tx = {
            'from': recipient,
            'to': router02_addr,
            'value': amount_in,
            'data': calldata,
            'chainId': 4663
        }

        gas_estimate = w3.eth.estimate_gas(tx)
        print(f"SIMULATION OK | Venue: UNISWAP_V3_USDG | gas: {gas_estimate}")
        return True

    except Exception as e:
        print(f"SIMULATION REVERT | Venue: UNISWAP_V3_USDG")
        print(f"Revert: {e}")
        return False


def force_simulate_v4_usdg_2hop(token_address: str, eth_amount: float = 0.0002, w3=None, recipient=None, fee2: int = 3000, hook2: str = PONS_V2_HOOK):
    print("=" * 70)
    print(f"FORCED SIMULATION: Graduated V4 USDG 2-HOP for {token_address}")
    print("=" * 70)

    if w3 is None:
        w3 = Web3(Web3.HTTPProvider('https://rpc.mainnet.chain.robinhood.com'))
    if recipient is None:
        recipient = "0x801F3F2822Af33A5A127aeEc4487882464AB4C31"

    token = w3.to_checksum_address(token_address)
    amount_in = w3.to_wei(eth_amount, 'ether')
    recipient = w3.to_checksum_address(recipient)
    min_out = 1
    weth = w3.to_checksum_address(WETH_ADDRESS)
    usdg = w3.to_checksum_address(USDG_ADDRESS)
    router_addr = w3.to_checksum_address(UNIVERSAL_ROUTER_ADDR)

    try:
        commands = bytes([0x0b, 0x10, 0x10])  # WRAP_ETH + V4 + V4

        wrap_input = eth_abi.encode(
            ['address', 'uint256'],
            [router_addr, amount_in]
        )

        # 2. WETH -> USDG
        hop1 = make_v4_swap_input(
            token_in=weth,
            token_out=usdg,
            amount_in=amount_in,
            min_out=1,
            recipient=router_addr,
            fee=500,
            tick_spacing=10,
            hook_addr="0x0000000000000000000000000000000000000000"
        )

        # 3. USDG -> Token
        hop2 = make_v4_swap_input(
            token_in=usdg,
            token_out=token,
            amount_in=1,
            min_out=min_out,
            recipient=recipient,
            fee=fee2,
            tick_spacing=60,
            hook_addr=hook2
        )

        inputs = [wrap_input, hop1, hop2]
        router = w3.eth.contract(address=router_addr, abi=UNIVERSAL_ROUTER_ABI)

        tx = router.functions.execute(
            commands,
            inputs,
            int(time.time()) + 600
        ).build_transaction({
            "from": recipient,
            "value": amount_in,
            "gas": 700000,
            "nonce": w3.eth.get_transaction_count(recipient),
            "chainId": 4663
        })

        gas_estimate = w3.eth.estimate_gas(tx)
        print(f"SIMULATION OK | Venue: UNISWAP_V4_USDG_2HOP | gas: {gas_estimate}")
        return True

    except Exception as e:
        print(f"SIMULATION REVERT | Venue: UNISWAP_V4_USDG_2HOP")
        print(f"Revert: {e}")
        return False


# ─── Standalone Sell Functions & Simulator ────────────────────────────────

def get_default_w3_and_account():
    from config import Config
    from chain_client import ChainClient
    cfg = Config()
    chain = ChainClient(cfg)
    return chain.w3, chain.account


def sell_eth_curve(token: str, amount_tokens: float, min_out: int = 1, w3=None, account=None):
    if w3 is None or account is None:
        w3, account = get_default_w3_and_account()
    token = w3.to_checksum_address(token)

    curve_addr = None
    if token.lower() == "0x928233827A025193A553DC805ADE16174Be7589f".lower():
        curve_addr = "0x35fe208A3F5400016E3E9C409bb9752cB596D2Dd"
    else:
        from config import Config
        from chain_client import ChainClient
        cfg = Config()
        trader = DexTrader(ChainClient(cfg), cfg)
        c, _, _ = asyncio.run(trader.resolve_token_curve(token))
        curve_addr = c

    if not curve_addr:
        print("Not a valid ETH curve")
        return None

    curve_addr = w3.to_checksum_address(curve_addr)
    token_contract = w3.eth.contract(address=token, abi=ERC20_ABI)
    try:
        decimals = token_contract.functions.decimals().call()
    except Exception:
        decimals = 18
    amount_in = int(amount_tokens * (10**decimals))

    allowance = token_contract.functions.allowance(account.address, curve_addr).call()
    if allowance < amount_in:
        approve_tx = token_contract.functions.approve(curve_addr, 2**256 - 1).build_transaction({
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            "gas": 80000,
            "chainId": 4663
        })
        signed = account.sign_transaction(approve_tx)
        raw = getattr(signed, 'raw_transaction', getattr(signed, 'rawTransaction', None))
        tx_h = w3.eth.send_raw_transaction(raw).hex()
        w3.eth.wait_for_transaction_receipt(tx_h, timeout=60)

    curve = w3.eth.contract(address=curve_addr, abi=PONS_CURVE_ABI)
    tx = curve.functions.sell(
        amount_in,
        min_out,
        account.address
    ).build_transaction({
        "from": account.address,
        "value": 0,
        "gas": 300000,
        "nonce": w3.eth.get_transaction_count(account.address),
        "chainId": 4663
    })
    return tx


def sell_usdg_curve(token: str, amount_tokens: float, min_out: int = 1, w3=None, account=None):
    if w3 is None or account is None:
        w3, account = get_default_w3_and_account()
    token = w3.to_checksum_address(token)

    curve_addr = None
    if token.lower() == "0x77f06AEE8aB51cF6347fA599D13cB6B97C53d4B6".lower():
        curve_addr = "0x1DB4E3fE3f941e4c19Cf87488dC653D8E9D6Dae4"
    else:
        from config import Config
        from chain_client import ChainClient
        cfg = Config()
        trader = DexTrader(ChainClient(cfg), cfg)
        c, _, _ = asyncio.run(trader.resolve_token_curve(token))
        curve_addr = c

    if not curve_addr:
        print("Not a valid USDG curve")
        return None

    curve_addr = w3.to_checksum_address(curve_addr)
    token_contract = w3.eth.contract(address=token, abi=ERC20_ABI)
    try:
        decimals = token_contract.functions.decimals().call()
    except Exception:
        decimals = 18
    amount_in = int(amount_tokens * (10**decimals))

    allowance = token_contract.functions.allowance(account.address, curve_addr).call()
    if allowance < amount_in:
        approve_tx = token_contract.functions.approve(curve_addr, 2**256 - 1).build_transaction({
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            "gas": 80000,
            "chainId": 4663
        })
        signed = account.sign_transaction(approve_tx)
        raw = getattr(signed, 'raw_transaction', getattr(signed, 'rawTransaction', None))
        tx_h = w3.eth.send_raw_transaction(raw).hex()
        w3.eth.wait_for_transaction_receipt(tx_h, timeout=60)

    curve = w3.eth.contract(address=curve_addr, abi=PONS_CURVE_ABI)
    tx = curve.functions.sell(
        amount_in,
        min_out,
        account.address
    ).build_transaction({
        "from": account.address,
        "value": 0,
        "gas": 300000,
        "nonce": w3.eth.get_transaction_count(account.address),
        "chainId": 4663
    })
    return tx


def sell_v3_weth(token: str, amount_tokens: float, min_out: int = 1, w3=None, account=None, fee: int = 10000):
    if w3 is None or account is None:
        w3, account = get_default_w3_and_account()
    token = w3.to_checksum_address(token)
    token_contract = w3.eth.contract(address=token, abi=ERC20_ABI)
    try:
        decimals = token_contract.functions.decimals().call()
    except Exception:
        decimals = 18
    amount_in = int(amount_tokens * (10**decimals))

    router = w3.to_checksum_address(UNISWAP_V3_SWAPROUTER02)
    allowance = token_contract.functions.allowance(account.address, router).call()
    if allowance < amount_in:
        approve_tx = token_contract.functions.approve(router, 2**256 - 1).build_transaction({
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            "gas": 80000,
            "chainId": 4663
        })
        signed = account.sign_transaction(approve_tx)
        raw = getattr(signed, 'raw_transaction', getattr(signed, 'rawTransaction', None))
        tx_h = w3.eth.send_raw_transaction(raw).hex()
        w3.eth.wait_for_transaction_receipt(tx_h, timeout=60)

    router_contract = w3.eth.contract(address=router, abi=SWAP_ROUTER02_ABI)
    params = (token, w3.to_checksum_address(WETH_ADDRESS), fee, account.address, amount_in, min_out, 0)
    calldata = router_contract.functions.exactInputSingle(params)._encode_transaction_data()
    tx = {
        "from": account.address,
        "to": router,
        "value": 0,
        "data": calldata,
        "gas": 350000,
        "nonce": w3.eth.get_transaction_count(account.address),
        "chainId": 4663
    }
    return tx


def sell_v3_usdg(token: str, amount_tokens: float, min_out: int = 1, w3=None, account=None, fee1: int = 3000, fee2: int = 500):
    if w3 is None or account is None:
        w3, account = get_default_w3_and_account()
    token = w3.to_checksum_address(token)
    token_contract = w3.eth.contract(address=token, abi=ERC20_ABI)
    try:
        decimals = token_contract.functions.decimals().call()
    except Exception:
        decimals = 18
    amount_in = int(amount_tokens * (10**decimals))

    router = w3.to_checksum_address(UNISWAP_V3_SWAPROUTER02)
    allowance = token_contract.functions.allowance(account.address, router).call()
    if allowance < amount_in:
        approve_tx = token_contract.functions.approve(router, 2**256 - 1).build_transaction({
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            "gas": 80000,
            "chainId": 4663
        })
        signed = account.sign_transaction(approve_tx)
        raw = getattr(signed, 'raw_transaction', getattr(signed, 'rawTransaction', None))
        tx_h = w3.eth.send_raw_transaction(raw).hex()
        w3.eth.wait_for_transaction_receipt(tx_h, timeout=60)

    # Path: Token -> (fee1) -> USDG -> (fee2) -> WETH
    path_bytes = (
        bytes.fromhex(token[2:]) +
        fee1.to_bytes(3, 'big') +
        bytes.fromhex(USDG_ADDRESS[2:]) +
        fee2.to_bytes(3, 'big') +
        bytes.fromhex(WETH_ADDRESS[2:])
    )

    router_contract = w3.eth.contract(address=router, abi=SWAP_ROUTER02_ABI)
    calldata = router_contract.functions.exactInput((path_bytes, account.address, amount_in, min_out))._encode_transaction_data()
    tx = {
        "from": account.address,
        "to": router,
        "value": 0,
        "data": calldata,
        "gas": 450000,
        "nonce": w3.eth.get_transaction_count(account.address),
        "chainId": 4663
    }
    return tx


def sell_token(token_address: str, amount_tokens: float, min_out: int = 1, w3=None, account=None):
    """Main sell function - automatically chooses the correct route"""
    if w3 is None or account is None:
        w3, account = get_default_w3_and_account()
    token = w3.to_checksum_address(token_address)

    from config import Config
    from chain_client import ChainClient
    cfg = Config()
    chain = ChainClient(cfg)
    if account:
        chain.account = account
    trader = DexTrader(chain, cfg)

    try:
        tx_hash, tokens_sold = asyncio.run(trader.sell_token(token, amount_tokens))
        if tx_hash:
            return tx_hash
        return None
    except Exception as e:
        print(f"Sell execution failed: {e}")
        return None


def force_simulate_sell(token_address: str, amount_tokens: float = 1000, w3=None, account=None):
    print("=" * 70)
    print(f"FORCED SELL SIMULATION for {token_address}")
    print("=" * 70)
    if w3 is None or account is None:
        w3, account = get_default_w3_and_account()
    try:
        tx = sell_token(token_address, amount_tokens, min_out=1, w3=w3, account=account)
        if tx is None:
            return False
        gas_estimate = w3.eth.estimate_gas(tx)
        print(f"SIMULATION OK | Sell gas: {gas_estimate}")
        return True
    except Exception as e:
        print(f"SIMULATION REVERT | {e}")
        return False

