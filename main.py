#!/usr/bin/env python3
"""
Solana Price Tracker & Alert Bot
Fetches real-time SOL/USD prices and dispatches alerts based on price boundaries and volatility.
"""

import os
import sys
import time
import signal
import logging
import argparse
from typing import Optional, Tuple
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

# Load optional .env file
load_dotenv()


# =====================================================================
# Configuration Setup
# =====================================================================

@dataclass
class BotConfig:
    poll_interval: int
    alert_high: Optional[float]
    alert_low: Optional[float]
    pct_change_threshold: Optional[float]
    cooldown_seconds: int
    webhook_url: Optional[str]


def parse_arguments() -> BotConfig:
    parser = argparse.ArgumentParser(
        description="Real-time Solana (SOL) price tracker and alert logger."
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=int(os.getenv("POLL_INTERVAL", 15)),
        help="Polling interval in seconds (default: 15)",
    )
    parser.add_argument(
        "--alert-high",
        type=float,
        default=float(os.getenv("ALERT_HIGH", 250.0)) if os.getenv("ALERT_HIGH") else None,
        help="Trigger alert when price goes above this USD value",
    )
    parser.add_argument(
        "--alert-low",
        type=float,
        default=float(os.getenv("ALERT_LOW", 150.0)) if os.getenv("ALERT_LOW") else None,
        help="Trigger alert when price falls below this USD value",
    )
    parser.add_argument(
        "--pct-change",
        type=float,
        dest="pct_change_threshold",
        default=float(os.getenv("PCT_CHANGE_THRESHOLD", 2.0)) if os.getenv("PCT_CHANGE_THRESHOLD") else None,
        help="Trigger alert when absolute percentage change between polls exceeds this value (e.g., 2.0)",
    )
    parser.add_argument(
        "--cooldown",
        type=int,
        dest="cooldown_seconds",
        default=int(os.getenv("COOLDOWN_SECONDS", 300)),
        help="Cooldown period in seconds to suppress duplicate alerts (default: 300)",
    )
    parser.add_argument(
        "--webhook",
        type=str,
        dest="webhook_url",
        default=os.getenv("DISCORD_WEBHOOK_URL", None),
        help="Optional Discord/Slack webhook URL for alerts",
    )

    args = parser.parse_args()
    return BotConfig(
        poll_interval=args.poll_interval,
        alert_high=args.alert_high,
        alert_low=args.alert_low,
        pct_change_threshold=args.pct_change_threshold,
        cooldown_seconds=args.cooldown_seconds,
        webhook_url=args.webhook_url,
    )


# =====================================================================
# Logging Setup
# =====================================================================

class ColorFormatter(logging.Formatter):
    """Custom formatter adding color to console logs for rapid visual alert parsing."""

    GREY = "\x1b[38;20m"
    GREEN = "\x1b[32;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    CYAN = "\x1b[36;20m"
    RESET = "\x1b[0m"

    FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

    FORMATS = {
        logging.DEBUG: GREY + FORMAT + RESET,
        logging.INFO: GREEN + FORMAT + RESET,
        logging.WARNING: YELLOW + FORMAT + RESET,
        logging.ERROR: RED + FORMAT + RESET,
        logging.CRITICAL: BOLD_RED + FORMAT + RESET,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno, self.FORMAT)
        formatter = logging.Formatter(log_fmt, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)


logger = logging.getLogger("SolanaTracker")
logger.setLevel(logging.INFO)
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(ColorFormatter())
logger.addHandler(ch)


# =====================================================================
# Price Fetching Service (Dual-Provider with Failover)
# =====================================================================

class PriceFetcher:
    """Fetches SOL price in USD with automatic API failover."""

    COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd&include_24hr_change=true"
    BINANCE_URL = "https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT"

    def __init__(self, timeout: int = 8):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "SolanaPriceTrackerBot/1.0"
        })

    def fetch_price(self) -> Tuple[Optional[float], Optional[str], Optional[float]]:
        """
        Attempts to fetch SOL price.
        Returns: (price_usd, source_name, 24h_change)
        """
        # Primary: CoinGecko
        try:
            resp = self.session.get(self.COINGECKO_URL, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                sol_data = data.get("solana", {})
                price = float(sol_data.get("usd"))
                change_24h = sol_data.get("usd_24h_change")
                return price, "CoinGecko", change_24h
            else:
                logger.warning(f"CoinGecko returned HTTP {resp.status_code}. Attempting fallback...")
        except requests.RequestException as e:
            logger.warning(f"CoinGecko request failed ({type(e).__name__}). Attempting fallback...")

        # Fallback: Binance Public API
        try:
            resp = self.session.get(self.BINANCE_URL, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                price = float(data.get("price"))
                return price, "Binance", None
            else:
                logger.error(f"Binance fallback failed with HTTP {resp.status_code}.")
        except requests.RequestException as e:
            logger.error(f"Binance request failed ({type(e).__name__}).")

        return None, None, None


# =====================================================================
# Alert Dispatcher
# =====================================================================

class AlertEngine:
    """Evaluates price conditions and dispatches alerts without spamming."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.last_price: Optional[float] = None
        self.last_alerts = {
            "high": 0.0,
            "low": 0.0,
            "pct_change": 0.0,
        }

    def _is_cooled_down(self, alert_key: str) -> bool:
        now = time.time()
        if now - self.last_alerts.get(alert_key, 0.0) >= self.config.cooldown_seconds:
            self.last_alerts[alert_key] = now
            return True
        return False

    def send_webhook(self, message: str):
        """Sends alert message to a Discord/Slack webhook if configured."""
        if not self.config.webhook_url:
            return
        try:
            payload = {"content": f"🚨 **Solana Price Alert** 🚨\n{message}"}
            requests.post(self.config.webhook_url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"Failed to post to webhook: {e}")

    def evaluate(self, current_price: float):
        """Checks configured conditions against the latest price."""
        # 1. High Threshold Alert
        if self.config.alert_high is not None and current_price >= self.config.alert_high:
            if self._is_cooled_down("high"):
                alert_msg = (
                    f"[HIGH THRESHOLD] SOL reached ${current_price:.2f}, "
                    f"crossing above target of ${self.config.alert_high:.2f}!"
                )
                logger.warning(alert_msg)
                self.send_webhook(alert_msg)

        # 2. Low Threshold Alert
        if self.config.alert_low is not None and current_price <= self.config.alert_low:
            if self._is_cooled_down("low"):
                alert_msg = (
                    f"[LOW THRESHOLD] SOL dropped to ${current_price:.2f}, "
                    f"breaking below target of ${self.config.alert_low:.2f}!"
                )
                logger.warning(alert_msg)
                self.send_webhook(alert_msg)

        # 3. Volatility / Percentage Shift Alert
        if self.last_price is not None and self.config.pct_change_threshold is not None:
            pct_delta = ((current_price - self.last_price) / self.last_price) * 100.0
            if abs(pct_delta) >= self.config.pct_change_threshold:
                if self._is_cooled_down("pct_change"):
                    direction = "SPIKE (+)" if pct_delta > 0 else "DIP (-)"
                    alert_msg = (
                        f"[VOLATILITY {direction}] Price changed by {pct_delta:+.2f}% "
                        f"(${self.last_price:.2f} -> ${current_price:.2f}) within polling window."
                    )
                    logger.warning(alert_msg)
                    self.send_webhook(alert_msg)

        self.last_price = current_price


# =====================================================================
# Main Application Loop
# =====================================================================

class SolanaTrackerBot:
    def __init__(self, config: BotConfig):
        self.config = config
        self.fetcher = PriceFetcher()
        self.alert_engine = AlertEngine(config)
        self.running = True

        # Register termination handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        logger.info("Shutdown signal received. Exiting tracker gracefully...")
        self.running = False

    def run(self):
        logger.info("Solana Price Tracker initialized.")
        logger.info(
            f"Active Thresholds -> High: ${self.config.alert_high or 'None'} | "
            f"Low: ${self.config.alert_low or 'None'} | "
            f"Volatility Trigger: ±{self.config.pct_change_threshold or 'None'}% | "
            f"Interval: {self.config.poll_interval}s"
        )

        while self.running:
            price, source, change_24h = self.fetcher.fetch_price()

            if price is not None:
                change_str = f" | 24h Change: {change_24h:+.2f}%" if change_24h is not None else ""
                logger.info(f"[{source}] SOL/USD: ${price:.2f}{change_str}")
                self.alert_engine.evaluate(price)
            else:
                logger.error("Unable to retrieve SOL price from any provider. Will retry on next tick.")

            # Interruptible sleep
            sleep_ticks = self.config.poll_interval * 10
            for _ in range(sleep_ticks):
                if not self.running:
                    break
                time.sleep(0.1)

        logger.info("Solana Price Tracker stopped.")


if __name__ == "__main__":
    configuration = parse_arguments()
    bot = SolanaTrackerBot(configuration)
    bot.run()
```