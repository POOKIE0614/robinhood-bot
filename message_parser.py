import re
import logging
from datetime import datetime
from typing import Optional, List, Any

from models import CallSignal

logger = logging.getLogger("copytrader")

class MessageParser:
    """Parses early call messages from Telegram."""

    def __init__(self):
        # Universal ticker pattern matching "$TICKER · robinhood" with any prefix (EARLY CALL, NARRATIVE, etc.)
        self.ticker_pattern = re.compile(
            r"\$([A-Za-z0-9_\u4e00-\u9fff\U00010000-\U0010ffff]+)\s*·\s*robinhood", 
            re.IGNORECASE
        )
        self.fallback_ticker_pattern = re.compile(
            r"(?:EARLY CALL|NARRATIVE|HIGH CONVICTION|GEM|ALPHA|CALL|SIGNAL)\s*[—–-]\s*\$?([A-Za-z0-9_\u4e00-\u9fff\U00010000-\U0010ffff]+)", 
            re.IGNORECASE
        )
        self.mcap_pattern = re.compile(r"Mcap:\s*\$?([\d.]+)([kKmM]?)")
        self.liq_pattern = re.compile(r"Liq:\s*\$?([\d.]+)([kKmM]?)\s*\|\s*([\d.]+)%")
        self.tax_pattern = re.compile(r"Tax:\s*B\s*([\d.]+)%\s*\|\s*S\s*([\d.]+)%")
        self.age_pattern = re.compile(r"Age:\s*(\d+)m")
        self.holders_pattern = re.compile(r"Holders:\s*([\d,]+)")
        self.volume_pattern = re.compile(r"Vol 24h:\s*\$?([\d.]+)([kKmM]?)")
        self.swaps_pattern = re.compile(r"(\d+)\s*swaps\s*\(5m\)")
        self.proof_pattern = re.compile(r"(\d+)\s*elite\s*\+\s*(\d+)\s*good")
        self.dex_pattern = re.compile(r"DEX:\s*(.+?)$", re.MULTILINE)
        
        # Address matching for raw text (42 chars, starting with 0x)
        self.address_pattern = re.compile(r"0x[a-fA-F0-9]{40}")

    def _parse_value(self, val: str, suffix: str) -> float:
        """Helper to convert strings like '79' and 'k' to 79000.0"""
        try:
            value = float(val)
            suffix = suffix.upper()
            if suffix == 'K':
                return value * 1000
            elif suffix == 'M':
                return value * 1000000
            return value
        except ValueError:
            return 0.0

    def parse(self, text: str, entities: List[Any], message_id: int, timestamp: datetime, buttons: Any = None, reply_markup: Any = None) -> Optional[CallSignal]:
        """Parses a message into a CallSignal if it's an alert/call."""
        if not text:
            return None
            
        # Must contain pool/token indicators (filters out hit/celebration messages)
        text_lower = text.lower()
        if not any(k in text_lower for k in ["pool info", "called at", "early call", "narrative", "mcap:"]):
            return None
            
        # Skip pure multiplier updates (e.g. "NBHOODS hit 2X")
        if " hit " in text_lower and "pool info" not in text_lower:
            return None

        try:
            # 1. Ticker
            ticker_match = self.ticker_pattern.search(text) or self.fallback_ticker_pattern.search(text)
            if not ticker_match:
                logger.debug(f"Msg {message_id}: Call header found but ticker pattern did not match.")
                return None
            ticker = ticker_match.group(1).upper()

            # 2. Extract address
            contract_address = None
            
            # Check inline buttons (telethon message.buttons or message.reply_markup)
            if buttons:
                for row in buttons:
                    if isinstance(row, list):
                        for btn in row:
                            url = getattr(btn, 'url', None) or getattr(btn, 'data', None)
                            if url and isinstance(url, str):
                                url_match = self.address_pattern.search(url)
                                if url_match:
                                    contract_address = url_match.group(0)
                                    break
                    elif hasattr(row, 'url') and row.url:
                        url_match = self.address_pattern.search(row.url)
                        if url_match:
                            contract_address = url_match.group(0)
                            break
                    if contract_address:
                        break

            # Check reply_markup rows if not found yet
            if not contract_address and reply_markup and hasattr(reply_markup, 'rows'):
                for row in reply_markup.rows:
                    if hasattr(row, 'buttons'):
                        for btn in row.buttons:
                            url = getattr(btn, 'url', None)
                            if url:
                                url_match = self.address_pattern.search(url)
                                if url_match:
                                    contract_address = url_match.group(0)
                                    break
                    if contract_address:
                        break

            # Check entities
            if not contract_address and entities:
                for entity in entities:
                    url = getattr(entity, 'url', None)
                    if url:
                        url_match = self.address_pattern.search(url)
                        if url_match:
                            contract_address = url_match.group(0)
                            break
            
            # Check raw text with multiple address handling
            if not contract_address:
                # Priority 1: Check for explicit "CA:" / "Contract:" / "Token:" tag
                ca_tag_match = re.search(r"(?:ca|contract|token|address)\s*[:=]?\s*(0x[a-fA-F0-9]{40})", text, re.IGNORECASE)
                if ca_tag_match:
                    contract_address = ca_tag_match.group(1)
                    logger.info(f"Msg {message_id}: Extracted CA-tagged contract address: {contract_address}")
                else:
                    all_addrs = self.address_pattern.findall(text)
                    if all_addrs:
                        # Exclude known system contract addresses (WETH, USDG, Routers)
                        system_addrs = {
                            "0x0bd7d308f8e1639fab988df18a8011f41eacad73", # WETH
                            "0x5fc5360d0400a0fd4f2af552add042d716f1d168", # USDG
                            "0x8876789976decbfcbbbe364623c63652db8c0904", # Universal Router
                            "0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e", # Pons V2 Factory
                        }
                        candidate_addrs = [a for a in all_addrs if a.lower() not in system_addrs]
                        if candidate_addrs:
                            contract_address = candidate_addrs[0]
                            if len(candidate_addrs) > 1:
                                logger.info(f"Msg {message_id}: Multiple 0x addresses found ({len(candidate_addrs)}). Selected candidate: {contract_address}")
                        else:
                            contract_address = all_addrs[0]
            
            # DexScreener Fallback API if address not in message
            if not contract_address:
                try:
                    import urllib.request
                    import json
                    req = urllib.request.Request(
                        f"https://api.dexscreener.com/latest/dex/search?q={ticker}",
                        headers={'User-Agent': 'Mozilla/5.0'}
                    )
                    res = json.loads(urllib.request.urlopen(req, timeout=3).read().decode('utf-8'))
                    pairs = res.get('pairs', [])
                    # First priority: robinhood chain pair matching ticker
                    for p in pairs:
                        if p.get('chainId') == 'robinhood' and p.get('baseToken', {}).get('symbol', '').upper() == ticker:
                            addr = p.get('baseToken', {}).get('address')
                            if addr and addr.startswith('0x') and len(addr) == 42:
                                contract_address = addr
                                logger.info(f"Resolved contract address for ${ticker} via DexScreener (Robinhood Chain): {contract_address}")
                                break
                    
                    # Second priority: any robinhood chain pair
                    if not contract_address:
                        for p in pairs:
                            if p.get('chainId') == 'robinhood':
                                addr = p.get('baseToken', {}).get('address')
                                if addr and addr.startswith('0x') and len(addr) == 42:
                                    contract_address = addr
                                    logger.info(f"Resolved contract address for ${ticker} via DexScreener (Robinhood Chain): {contract_address}")
                                    break
                except Exception as e:
                    logger.debug(f"DexScreener API fallback lookup failed for ${ticker}: {e}")
            
            # 3. Mcap
            mcap_usd = None
            mcap_match = self.mcap_pattern.search(text)
            if mcap_match:
                mcap_usd = self._parse_value(mcap_match.group(1), mcap_match.group(2))

            # 4. Liquidity
            liquidity_usd, liquidity_pct = None, None
            liq_match = self.liq_pattern.search(text)
            if liq_match:
                liquidity_usd = self._parse_value(liq_match.group(1), liq_match.group(2))
                try:
                    liquidity_pct = float(liq_match.group(3))
                except ValueError:
                    pass

            # 5. Tax
            buy_tax, sell_tax = 0.0, 0.0
            tax_match = self.tax_pattern.search(text)
            if tax_match:
                try:
                    buy_tax = float(tax_match.group(1))
                    sell_tax = float(tax_match.group(2))
                except ValueError:
                    pass

            # 6. Age
            token_age_minutes = None
            age_match = self.age_pattern.search(text)
            if age_match:
                try:
                    token_age_minutes = int(age_match.group(1))
                except ValueError:
                    pass

            # 7. Holders
            holders = None
            holders_match = self.holders_pattern.search(text)
            if holders_match:
                try:
                    holders = int(holders_match.group(1).replace(",", ""))
                except ValueError:
                    pass

            # 8. Volume
            volume_24h = None
            vol_match = self.volume_pattern.search(text)
            if vol_match:
                volume_24h = self._parse_value(vol_match.group(1), vol_match.group(2))

            # 9. Swaps
            swaps_5m = None
            swaps_match = self.swaps_pattern.search(text)
            if swaps_match:
                try:
                    swaps_5m = int(swaps_match.group(1))
                except ValueError:
                    pass
            
            # 10. Proof
            elite_wallets, good_wallets = 0, 0
            proof_match = self.proof_pattern.search(text)
            if proof_match:
                try:
                    elite_wallets = int(proof_match.group(1))
                    good_wallets = int(proof_match.group(2))
                except ValueError:
                    pass

            # 11. DEX
            dex = ""
            dex_match = self.dex_pattern.search(text)
            if dex_match:
                dex = dex_match.group(1).strip()

            signal = CallSignal(
                ticker=ticker,
                contract_address=contract_address,
                mcap_usd=mcap_usd,
                liquidity_usd=liquidity_usd,
                liquidity_pct=liquidity_pct,
                buy_tax=buy_tax,
                sell_tax=sell_tax,
                token_age_minutes=token_age_minutes,
                holders=holders,
                volume_24h=volume_24h,
                swaps_5m=swaps_5m,
                elite_wallets=elite_wallets,
                good_wallets=good_wallets,
                dex=dex,
                raw_text=text,
                timestamp=timestamp,
                message_id=message_id
            )
            
            logger.info(f"Successfully parsed EARLY CALL for {ticker}. Addr: {contract_address}")
            return signal

        except Exception as e:
            logger.error(f"Failed to parse EARLY CALL message {message_id}: {str(e)}", exc_info=True)
            return None
