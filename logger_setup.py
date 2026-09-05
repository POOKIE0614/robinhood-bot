import logging
from logging.handlers import RotatingFileHandler
import os

class TradeFilter(logging.Filter):
    def filter(self, record):
        return getattr(record, 'is_trade', False)

def setup_logging():
    logger = logging.getLogger("copytrader")
    logger.setLevel(logging.DEBUG)

    os.makedirs("logs", exist_ok=True)

    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

    # Console Handler (INFO) with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    class ColorFormatter(logging.Formatter):
        grey = "\x1b[38;20m"
        yellow = "\x1b[33;20m"
        red = "\x1b[31;20m"
        bold_red = "\x1b[31;1m"
        reset = "\x1b[0m"
        format_str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

        FORMATS = {
            logging.DEBUG: grey + format_str + reset,
            logging.INFO: grey + format_str + reset,
            logging.WARNING: yellow + format_str + reset,
            logging.ERROR: red + format_str + reset,
            logging.CRITICAL: bold_red + format_str + reset
        }

        def format(self, record):
            log_fmt = self.FORMATS.get(record.levelno)
            formatter = logging.Formatter(log_fmt)
            return formatter.format(record)

    console_handler.setFormatter(ColorFormatter())

    # File Handler (DEBUG)
    file_handler = RotatingFileHandler(
        "logs/bot.log", maxBytes=5*1024*1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(file_formatter)

    # Trade File Handler
    trade_handler = logging.FileHandler("logs/trades.log", encoding="utf-8")
    trade_handler.setLevel(logging.INFO)
    trade_handler.setFormatter(file_formatter)
    trade_handler.addFilter(TradeFilter())

    if not logger.handlers:
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
        logger.addHandler(trade_handler)

    return logger
