"""
Calcul des indicateurs techniques utilisés par Nato Trade.
Utilise la librairie `ta` (Technical Analysis) qui s'appuie sur pandas.
"""

import pandas as pd
from ta.trend import EMAIndicator, ADXIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands

from . import config


def add_trend_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute EMA rapide/lente et ADX. Utilisé sur H1/M30 (plan d'analyste)."""
    df = df.copy()
    df["ema_fast"] = EMAIndicator(df["close"], window=config.EMA_FAST_PERIOD).ema_indicator()
    df["ema_slow"] = EMAIndicator(df["close"], window=config.EMA_SLOW_PERIOD).ema_indicator()

    adx_indicator = ADXIndicator(df["high"], df["low"], df["close"], window=config.ADX_PERIOD)
    df["adx"] = adx_indicator.adx()
    return df


def add_entry_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute RSI, MACD, Bollinger Bands. Utilisé sur M15/M5/M1 (entrée)."""
    df = df.copy()
    df["rsi"] = RSIIndicator(df["close"], window=config.RSI_PERIOD).rsi()

    macd_indicator = MACD(
        df["close"],
        window_fast=config.MACD_FAST,
        window_slow=config.MACD_SLOW,
        window_sign=config.MACD_SIGNAL,
    )
    df["macd"] = macd_indicator.macd()
    df["macd_signal"] = macd_indicator.macd_signal()
    df["macd_hist"] = macd_indicator.macd_diff()

    bb_indicator = BollingerBands(
        df["close"], window=config.BOLLINGER_PERIOD, window_dev=config.BOLLINGER_STD_DEV
    )
    df["bb_high"] = bb_indicator.bollinger_hband()
    df["bb_low"] = bb_indicator.bollinger_lband()
    df["bb_width"] = bb_indicator.bollinger_wband()
    return df


def get_trend_direction(df: pd.DataFrame) -> str:
    """
    Détermine la direction de tendance sur la dernière bougie close.
    Retourne "haussier", "baissier" ou "neutre".
    """
    last = df.iloc[-1]

    if last["adx"] < config.ADX_TREND_THRESHOLD:
        return "neutre"

    if last["close"] > last["ema_fast"] > last["ema_slow"]:
        return "haussier"
    if last["close"] < last["ema_fast"] < last["ema_slow"]:
        return "baissier"
    return "neutre"


def is_volatility_excessive(df: pd.DataFrame) -> bool:
    """
    Filtre de sécurité basé sur les Bollinger Bands.
    """
    recent = df["bb_width"].dropna().tail(50)
    if len(recent) < 10:
        return False

    current_width = recent.iloc[-1]
    average_width = recent.mean()

    if average_width == 0:
        return False

    return current_width > average_width * config.BOLLINGER_SQUEEZE_FILTER_MULTIPLIER
