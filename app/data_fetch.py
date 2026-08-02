"""
Recuperation des donnees de marche depuis Twelve Data.
Gere les appels API et la mise en forme des bougies (OHLC) en DataFrame pandas.
"""

import time
import logging
import requests
import pandas as pd

from . import config

logger = logging.getLogger("nato_trade.data_fetch")

_MIN_SECONDS_BETWEEN_CALLS = 8.0
_last_call_ts = 0.0


def _respect_rate_limit():
    global _last_call_ts
    elapsed = time.time() - _last_call_ts
    if elapsed < _MIN_SECONDS_BETWEEN_CALLS:
        time.sleep(_MIN_SECONDS_BETWEEN_CALLS - elapsed)
    _last_call_ts = time.time()


def fetch_candles(symbol: str, interval: str, output_size: int = 200) -> pd.DataFrame:
    _respect_rate_limit()

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": output_size,
        "apikey": config.TWELVE_DATA_API_KEY,
        "order": "ASC",
    }

    try:
        response = requests.get(
            f"{config.TWELVE_DATA_BASE_URL}/time_series", params=params, timeout=15
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        logger.error("Erreur reseau Twelve Data pour %s/%s: %s", symbol, interval, exc)
        return pd.DataFrame()

    if payload.get("status") == "error":
        logger.error(
            "Erreur API Twelve Data pour %s/%s: %s",
            symbol,
            interval,
            payload.get("message"),
        )
        return pd.DataFrame()

    values = payload.get("values", [])
    if not values:
        logger.warning("Aucune donnee recue pour %s/%s", symbol, interval)
        return pd.DataFrame()

    df = pd.DataFrame(values)
    df["datetime"] = pd.to_datetime(df["datetime"])
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")

    return df.sort_values("datetime").reset_index(drop=True)
