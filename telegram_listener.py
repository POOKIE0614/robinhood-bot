import asyncio
import logging
import os
from typing import Callable, Awaitable, Optional

from telethon import TelegramClient, events, errors

from config import Config
from message_parser import MessageParser
from models import CallSignal

logger = logging.getLogger("copytrader")

class TelegramListener:
    """Listens to a specific Telegram channel for early calls."""

    def __init__(self, config: Config, parser: MessageParser, on_signal: Callable[[CallSignal], Awaitable[None]]):
        self.config = config
        self.parser = parser
        self.on_signal = on_signal
        self.client: Optional[TelegramClient] = None
        self.is_running = False
        self._handler_registered = False
        self._heartbeat_task: Optional[asyncio.Task] = None

    async def _keep_alive_heartbeat(self):
        """Sends periodic lightweight pings to prevent Windows socket timeout ([WinError 121])."""
        while self.is_running:
            try:
                await asyncio.sleep(45)
                if self.client and self.client.is_connected():
                    await self.client.get_me()
                    logger.debug("Telegram connection heartbeat ping OK.")
            except (asyncio.CancelledError, GeneratorExit):
                break
            except Exception as e:
                logger.debug(f"Heartbeat ping notice: {e}")

    async def start(self):
        """Starts the Telegram listener and registers the event handler."""
        self.is_running = True
        
        # Instantiate TelegramClient in the active running event loop
        if self.client is None:
            session_dir = getattr(self.config, "BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
            session_path = os.path.join(session_dir, "robinhood_copy_trader_session")
            self.client = TelegramClient(
                session_path,
                self.config.TELEGRAM_API_ID,
                self.config.TELEGRAM_API_HASH,
                connection_retries=None,
                auto_reconnect=True,
                retry_delay=2,
                timeout=15,
                request_retries=5
            )

        # Start keep-alive heartbeat
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._keep_alive_heartbeat())
        
        while self.is_running:
            try:
                if not self.client.is_connected():
                    logger.info("Connecting to Telegram client...")
                    await self.client.start(phone=self.config.TELEGRAM_PHONE)
                
                if not self._handler_registered or not self.client.is_connected():
                    logger.info(f"Resolving channel: {self.config.CHANNEL_USERNAME}")
                    channel = await self.client.get_entity(self.config.CHANNEL_USERNAME)
                    
                    try:
                        self.client.remove_event_handler(self._handle_new_message)
                    except Exception:
                        pass

                    self.client.add_event_handler(
                        self._handle_new_message, 
                        events.NewMessage(chats=[channel])
                    )
                    self._handler_registered = True
                    logger.info("Telegram listener active. Listening for EARLY CALL alerts...")

                await self.client.run_until_disconnected()
                
            except errors.FloodWaitError as e:
                self._handler_registered = False
                logger.warning(f"Flood wait error. Waiting {e.seconds} seconds before reconnecting...")
                await asyncio.sleep(e.seconds)
            except (OSError, ConnectionError, asyncio.TimeoutError) as e:
                self._handler_registered = False
                logger.warning(f"Network socket timeout/drop ([WinError 121]/ConnectionError: {e}). Re-establishing connection in 3s...")
                try:
                    if self.client:
                        await self.client.disconnect()
                except Exception:
                    pass
                await asyncio.sleep(3)
            except Exception as e:
                self._handler_registered = False
                err_msg = str(e)
                if "database is locked" in err_msg:
                    logger.warning("Telegram session database lock detected (likely concurrent instance). Waiting 5s for lock to clear...")
                    await asyncio.sleep(5)
                else:
                    logger.warning(f"Connection dropped ({e}). Auto-reconnecting in 3 seconds...")
                    try:
                        if self.client:
                            await self.client.disconnect()
                    except Exception:
                        pass
                    await asyncio.sleep(3)

    async def stop(self):
        """Gracefully stops the Telegram listener."""
        self.is_running = False
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        logger.info("Stopping Telegram client...")
        if self.client and self.client.is_connected():
            await self.client.disconnect()
        logger.info("Telegram client stopped.")

    async def _handle_new_message(self, event):
        """Internal handler for new messages."""
        try:
            text = event.message.message
            message_id = event.message.id
            timestamp = event.message.date
            entities = event.message.entities

            buttons = getattr(event.message, 'buttons', None)
            reply_markup = getattr(event.message, 'reply_markup', None)

            logger.debug(f"Received message {message_id} from channel.")
            
            signal = self.parser.parse(
                text=text,
                entities=entities,
                message_id=message_id,
                timestamp=timestamp,
                buttons=buttons,
                reply_markup=reply_markup
            )
            
            if signal:
                logger.info(f"Valid CallSignal extracted for {signal.ticker}.")
                # Call the async callback
                try:
                    await self.on_signal(signal)
                except Exception as e:
                    logger.error(f"Error executing on_signal callback for {signal.ticker}: {str(e)}", exc_info=True)
                    
        except Exception as e:
            logger.error(f"Error handling new message: {str(e)}", exc_info=True)
