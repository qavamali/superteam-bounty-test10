# Solana Price Tracker & Alert Bot

A production-ready, resilient Python bot designed to monitor the real-time price of Solana (SOL) in USD, evaluate dynamic threshold and volatility triggers, and log structured alerts. The bot supports multi-provider API redundancy (CoinGecko and Binance), optional Discord/Slack webhook notifications, and automated alert cooldowns.

---

## Architecture Overview

```
                                +---------------------------+
                                |     Solana Tracker Bot    |
                                +-------------+-------------+
                                              |
                     +------------------------+------------------------+
                     |                                                 |
         [Primary Data Provider]                            [Fallback Provider]
         CoinGecko Public v3 API                             Binance Public API
                     |                                                 |
                     +------------------------+------------------------+
                                              |
                                      Normalized Price
                                              |
                                              v
                                   +---------------------+
                                   |    Alert Engine     |
                                   |  - High Threshold   |
                                   |  - Low Threshold    |
                                   |  - Rapid % Change   |
                                   +----------+----------+
                                              |
                         +--------------------+--------------------+
                         |                                         |
                         v                                         v
               [Console Logger]                           [Discord/Slack Webhook]
             (Colorized Terminal)                           (Optional Real-time)
```

The system employs a polling worker loop wrapped in graceful interrupt handlers:
1. **Redundant Price Fetching:** Attempts to fetch prices from CoinGecko. In the event of network anomalies, HTTP errors, or rate limits (HTTP 429), it automatically falls back to Binance API.
2. **Alert Rules Engine:** Evaluates static bounds (Take-Profit/Resistance, Stop-Loss/Support) and dynamic relative volatility (`%` move across consecutive ticks).
3. **Spam Mitigation:** Implements an alert cooldown timer per alert category to prevent alert fatigue.

---

## Features

- **High-Resilience Price Fetching:** Automatic failover between CoinGecko and Binance.
- **Configurable Alert Types:**
  - **Upper Bound (Bullish / Resistance):** Triggers when SOL breaks above a defined price.
  - **Lower Bound (Bearish / Support):** Triggers when SOL breaks below a defined price.
  - **Volatility Spike:** Triggers on relative percentage changes (e.g., $\ge \pm 2\%$ move since last poll).
- **Notification Channels:** Colorized console logging via Python's standard `logging` library, plus optional Discord/Slack webhook dispatcher.
- **Graceful Lifecycle Management:** Handles `SIGINT` (Ctrl+C) and `SIGTERM` signals for clean exits.
- **Environment & CLI Support:** Configure via `.env` file or direct command-line arguments.

---

## Prerequisites

- **Python:** 3.9 or higher
- **Package Manager:** `pip`

---

## Installation

1. **Clone the repository or save the project files:**
   ```bash
   mkdir solana-price-tracker && cd solana-price-tracker
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install requests python-dotenv
   ```

4. **Set up Environment Variables (Optional):**
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` to configure price thresholds and interval defaults:
   ```env
   POLL_INTERVAL=15
   ALERT_HIGH=250.0
   ALERT_LOW=180.0
   PCT_CHANGE_THRESHOLD=1.5
   COOLDOWN_SECONDS=300
   DISCORD_WEBHOOK_URL=
   ```

---

## Usage

### Run with Default Settings
Reads directly from `.env` or internal defaults:
```bash
python solana_price_tracker.py
```

### Run with Command-Line Overrides
You can override any threshold or interval at runtime:
```bash
python solana_price_tracker.py \
  --poll-interval 10 \
  --alert-high 220.0 \
  --alert-low 190.0 \
  --pct-change 2.0 \
  --cooldown 120
```

### CLI Flag Reference
| Flag | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--poll-interval` | `int` | Delay between price checks in seconds | `15` |
| `--alert-high` | `float` | Price ceiling threshold (USD) | `250.0` |
| `--alert-low` | `float` | Price floor threshold (USD) | `150.0` |
| `--pct-change` | `float` | Percent shift threshold trigger | `2.0` |
| `--cooldown` | `int` | Mute duplicate alerts for N seconds | `300` |
| `--webhook` | `str` | Discord/Slack Webhook URL for alerts | `None` |

---

## Example Log Output

```text
2025-05-18 14:00:00 [INFO] Solana Price Tracker initialized. Tracking SOL/USD...
2025-05-18 14:00:00 [INFO] Configuration: High: $220.00 | Low: $190.00 | Volatility: ±2.0% | Interval: 10s
2025-05-18 14:00:01 [INFO] [CoinGecko] SOL/USD: $205.42 | 24h Change: +3.41%
2025-05-18 14:00:11 [INFO] [CoinGecko] SOL/USD: $205.80 | Δ: +0.18%
2025-05-18 14:00:21 [ALERT] [HIGH THRESHOLD] SOL price $221.15 exceeded high target of $220.00!
2025-05-18 14:00:31 [ALERT] [VOLATILITY SPIKE] Significant move detected: +2.12% shift ($205.80 -> $210.16)
2025-05-18 14:00:41 [WARNING] [CoinGecko] Request timed out. Switching to Binance fallback...
2025-05-18 14:00:42 [INFO] [Binance] SOL/USD: $210.30
```