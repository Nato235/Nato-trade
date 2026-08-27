"""
Configuration centrale de Nato Trade.
Toutes les valeurs ajustables du bot sont ici pour faciliter les réglages
sans devoir modifier le code métier.
"""

import os

# --- API Twelve Data ---
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")
TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"

# --- Notifications ntfy.sh ---
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "nato-trade-CHANGE-MOI")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

# --- Actifs suivis (7 actifs, sans l'or) ---
FOREX_ASSETS = ["EUR/USD", "GBP/USD", "USD/JPY"]
CRYPTO_ASSETS = ["BTC/USD", "ETH/USD", "XRP/USD"]
ASSETS = FOREX_ASSETS + CRYPTO_ASSETS

# --- Horaires d'activité ---
TRADING_TIMEZONE = "Africa/Ndjamena"
FOREX_ACTIVE_DAYS = {0, 1, 2, 3, 4}
FOREX_ACTIVE_HOUR_START = 8
FOREX_ACTIVE_HOUR_END = 21

# --- Timeframes ---
TIMEFRAMES_TREND = ["1h", "30min"]
TIMEFRAMES_ENTRY = ["15min", "5min", "1min"]

# --- Mode scalping ---
SCALPING_ENABLED = os.environ.get("SCALPING_ENABLED", "false").lower() == "true"
SCALPING_TIMEFRAMES = ["5min", "1min"]
SCALPING_TP_SL_RATIO_MIN = 1.0

# --- Règle de confirmation (mode prudent assoupli) ---
CONFIRMATIONS_REQUIRED = 2
CONFIRMATIONS_TOTAL = 4

# --- Ratio risque/rendement minimum (mode prudent assoupli) ---
RR_RATIO_MIN = 1.2

# --- Indicateurs : périodes ---
EMA_FAST_PERIOD = 50
EMA_SLOW_PERIOD = 200
ADX_PERIOD = 14
ADX_TREND_THRESHOLD = 20

RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

BOLLINGER_PERIOD = 20
BOLLINGER_STD_DEV = 2
BOLLINGER_SQUEEZE_FILTER_MULTIPLIER = 2.5

# --- Fréquence d'analyse (en secondes) ---
POLL_INTERVAL_TREND = 30 * 60
POLL_INTERVAL_ENTRY = 60

# --- Base de données ---
DATABASE_PATH = os.environ.get("DATABASE_PATH", "./nato_trade.db")
