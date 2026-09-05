import asyncio
import logging
import time
from typing import Dict, Any, Optional
import aiohttp
from web3 import Web3
from web3.exceptions import Web3Exception, TransactionNotFound

logger = logging.getLogger("copytrader")

ERC20_ABI = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}
]

class ChainClient:
    def __init__(self, config):
        self.config = config
        self.primary_rpc = getattr(self.config, 'RPC_URL', "https://silent-clean-tent.robinhood-mainnet.quiknode.pro/fb9742dcdbac8e3afbacc17fc8859e433a719aa1/")
        self.wss_rpc = getattr(self.config, 'RPC_WSS_URL', "wss://silent-clean-tent.robinhood-mainnet.quiknode.pro/fb9742dcdbac8e3afbacc17fc8859e433a719aa1/")
        self.fallback_rpc = getattr(self.config, 'FALLBACK_RPC_URL', "https://rpc.mainnet.chain.robinhood.com")
        self.chain_id = int(getattr(self.config, 'CHAIN_ID', 4663))

        self.w3 = Web3(Web3.HTTPProvider(
            self.primary_rpc, 
            request_kwargs={'timeout': 10}
        ))
        self.fallback_w3 = Web3(Web3.HTTPProvider(
            self.fallback_rpc,
            request_kwargs={'timeout': 10}
        ))
        
        # Test connection & fallback if needed
        try:
            if not self.w3.is_connected():
                logger.warning(f"Primary RPC unreachable, switching to fallback RPC: {self.fallback_rpc}")
                self.w3 = self.fallback_w3
        except Exception as e:
            logger.warning(f"Error connecting to primary RPC ({e}), switching to fallback: {self.fallback_rpc}")
            self.w3 = self.fallback_w3

        self.account = self.w3.eth.account.from_key(self.config.PRIVATE_KEY) if hasattr(self.config, 'PRIVATE_KEY') and self.config.PRIVATE_KEY else None
        self._eth_price_usd: Optional[float] = None
        self._eth_price_timestamp: float = 0
        self._price_cache_ttl = 60

    async def _run_in_thread(self, func, *args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    async def _retry(self, func, *args, **kwargs):
        for attempt in range(3):
            try:
                return await self._run_in_thread(func, *args, **kwargs)
            except Exception as e:
                err_str = str(e)
                # Contract reverts on view probes are normal (e.g. pool not graduated yet)
                if "execution reverted" in err_str:
                    logger.debug(f"Contract view call returned revert: {e}")
                    raise
                logger.warning(f"Network error in chain call (attempt {attempt + 1}/3): {e}")
                if attempt == 1 and hasattr(self, 'fallback_w3'):
                    logger.warning(f"Switching active provider to fallback RPC: {self.fallback_rpc}")
                    self.w3 = self.fallback_w3
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5)

    async def get_eth_balance(self) -> float:
        if getattr(self.config, 'DRY_RUN', True) and not self.account:
            logger.info("[DRY RUN] No private key provided, using simulated balance of 0.0200 ETH ($50.00)")
            return 0.02
        if not self.account:
            return 0.0
        try:
            balance_wei = await self._retry(self.w3.eth.get_balance, self.account.address)
            return float(self.w3.from_wei(balance_wei, 'ether'))
        except Exception as e:
            if getattr(self.config, 'DRY_RUN', True):
                logger.warning(f"[DRY RUN] Could not fetch live on-chain balance ({e}), using simulated 0.0200 ETH ($50.00)")
                return 0.02
            raise

    async def get_token_balance(self, token_address: str) -> float:
        if not self.account:
            return 0.0
        token_address = self.w3.to_checksum_address(token_address)
        contract = self.w3.eth.contract(address=token_address, abi=ERC20_ABI)
        balance_raw = await self._retry(contract.functions.balanceOf(self.account.address).call)
        decimals = await self.get_token_decimals(token_address)
        return balance_raw / (10 ** decimals)
        
    async def get_eth_price_usd(self) -> float:
        now = time.time()
        if self._eth_price_usd and (now - self._eth_price_timestamp) < self._price_cache_ttl:
            return self._eth_price_usd
            
        timeout = aiohttp.ClientTimeout(total=3)
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        # Source 1: Coinbase
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get("https://api.coinbase.com/v2/prices/ETH-USD/spot") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        price = float(data["data"]["amount"])
                        self._eth_price_usd = price
                        self._eth_price_timestamp = now
                        return price
        except Exception:
            pass

        # Source 2: Binance
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get("https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        price = float(data["price"])
                        self._eth_price_usd = price
                        self._eth_price_timestamp = now
                        return price
        except Exception:
            pass

        # Source 3: CoinGecko
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        price = float(data["ethereum"]["usd"])
                        self._eth_price_usd = price
                        self._eth_price_timestamp = now
                        return price
        except Exception:
            pass
            
        if self._eth_price_usd:
            return self._eth_price_usd
        return 2500.0  # Fallback default

    async def usd_to_eth(self, usd_amount: float) -> float:
        price = await self.get_eth_price_usd()
        return usd_amount / price

    async def eth_to_usd(self, eth_amount: float) -> float:
        price = await self.get_eth_price_usd()
        return eth_amount * price

    async def get_nonce(self) -> int:
        if not self.account:
            raise ValueError("No private key configured")
        return await self._retry(self.w3.eth.get_transaction_count, self.account.address, 'pending')

    async def estimate_gas(self, tx: Dict[str, Any]) -> int:
        base_estimate = await self._retry(self.w3.eth.estimate_gas, tx)
        return int(base_estimate * getattr(self.config, 'GAS_MULTIPLIER', 1.2))

    async def send_transaction(self, tx: Dict[str, Any]) -> str:
        if getattr(self.config, 'DRY_RUN', True):
            logger.info(f"[DRY RUN] Would send transaction: {tx}")
            return f"DRY_RUN_0x{int(time.time())}"
            
        if not self.account:
            raise ValueError("No private key configured")
            
        if 'nonce' not in tx:
            tx['nonce'] = await self.get_nonce()
            
        if 'gas' not in tx:
            tx['gas'] = await self.estimate_gas(tx)
            
        if 'chainId' not in tx:
            tx['chainId'] = 4663

        # EIP-1559 Dynamic Gas Management with Safety Multiplier
        gas_mult = float(getattr(self.config, 'GAS_MULTIPLIER', 1.3))
        if 'maxFeePerGas' not in tx and 'gasPrice' not in tx:
            try:
                latest_block = await self._retry(self.w3.eth.get_block, 'latest')
                base_fee = latest_block.get('baseFeePerGas', None)
                if base_fee:
                    max_priority = int(base_fee * 0.1) or self.w3.to_wei(0.01, 'gwei')
                    max_fee = int(base_fee * max(1.3, gas_mult)) + max_priority
                    tx['maxFeePerGas'] = max_fee
                    tx['maxPriorityFeePerGas'] = max_priority
                else:
                    raw_gp = await self._retry(lambda: self.w3.eth.gas_price)
                    tx['gasPrice'] = int(raw_gp * max(1.3, gas_mult))
            except Exception:
                raw_gp = await self._retry(lambda: self.w3.eth.gas_price)
                tx['gasPrice'] = int(raw_gp * max(1.3, gas_mult))
        elif 'gasPrice' in tx:
            tx['gasPrice'] = int(tx['gasPrice'] * max(1.3, gas_mult))
            
        signed_tx = self.w3.eth.account.sign_transaction(tx, private_key=self.account.key)
        raw_tx_bytes = getattr(signed_tx, 'raw_transaction', getattr(signed_tx, 'rawTransaction', None))
        tx_hash = await self._retry(self.w3.eth.send_raw_transaction, raw_tx_bytes)
        hash_hex = self.w3.to_hex(tx_hash)
        logger.info(f"Transaction sent: {hash_hex}")
        return hash_hex

    async def wait_for_receipt(self, tx_hash: str, timeout: int = 60) -> Dict[str, Any]:
        if tx_hash.startswith("DRY_RUN_"):
            return {"status": 1, "transactionHash": tx_hash}
            
        start = time.time()
        while time.time() - start < timeout:
            try:
                receipt = await self._run_in_thread(self.w3.eth.get_transaction_receipt, tx_hash)
                if receipt:
                    return receipt
            except TransactionNotFound:
                pass
            except Exception as e:
                logger.warning(f"Error waiting for receipt: {e}")
            await asyncio.sleep(2)
            
        raise TimeoutError(f"Transaction {tx_hash} receipt not found after {timeout} seconds")

    async def get_token_decimals(self, token_address: str) -> int:
        token_address = self.w3.to_checksum_address(token_address)
        contract = self.w3.eth.contract(address=token_address, abi=ERC20_ABI)
        return await self._retry(contract.functions.decimals().call)

    async def approve_token(self, token_address: str, spender: str, amount: int) -> str:
        token_address = self.w3.to_checksum_address(token_address)
        spender = self.w3.to_checksum_address(spender)
        
        contract = self.w3.eth.contract(address=token_address, abi=ERC20_ABI)
        allowance = await self._retry(contract.functions.allowance(self.account.address, spender).call)
        
        if allowance >= amount:
            logger.info(f"Token {token_address} already approved for {spender}")
            return "ALREADY_APPROVED"
            
        if getattr(self.config, 'DRY_RUN', True):
            logger.info(f"[DRY RUN] Would approve {amount} of {token_address} for {spender}")
            return f"DRY_RUN_APPROVE_0x{int(time.time())}"
            
        tx = contract.functions.approve(spender, amount).build_transaction({
            'from': self.account.address,
            'gasPrice': await self._retry(lambda: self.w3.eth.gas_price)
        })
        
        logger.info(f"Approving token {token_address} for spender {spender}")
        tx_hash = await self.send_transaction(tx)
        if not tx_hash.startswith("DRY_RUN_"):
            await self.wait_for_receipt(tx_hash)
        return tx_hash


if __name__ == '__main__':
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider("https://silent-clean-tent.robinhood-mainnet.quiknode.pro/fb9742dcdbac8e3afbacc17fc8859e433a719aa1/"))
    print("Connected:", w3.is_connected())
    print("Chain ID:", w3.eth.chain_id)   # must print 4663

