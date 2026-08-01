"""
Moteur de décision de Nato Trade.
Combine tendance (H1/M30), confirmation d'entrée (M15/M5/M1) et filtre de
volatilité pour décider si un signal doit être émis, puis calcule SL/TP.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from . import config, indicators, patterns

logger = logging.getLogger("nato_trade.signals")


@dataclass
class Signal:
    asset: str
    timeframe: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    rr_ratio: float
    confirmations: list = field(default_factory=list)
    high_confidence: bool = False
    mode: str = "prudent"


def _check_rsi_confirmation(df: pd.DataFrame, direction: str) -> bool:
    last_rsi = df["rsi"].iloc[-1]
    if direction == "achat":
        return last_rsi < config.RSI_OVERSOLD + 10
    return last_rsi > config.RSI_OVERBOUGHT - 10


def _check_macd_confirmation(df: pd.DataFrame, direction: str) -> bool:
    hist = df["macd_hist"].iloc[-1]
    prev_hist = df["macd_hist"].iloc[-2]
    if direction == "achat":
        return hist > 0 and hist > prev_hist
    return hist < 0 and hist < prev_hist


def _check_structure_confirmation(df: pd.DataFrame, direction: str) -> bool:
    last = df.iloc[-1]
    body = abs(last["close"] - last["open"])
    if body == 0:
        return False

    if direction == "achat":
        lower_wick = min(last["open"], last["close"]) - last["low"]
        return lower_wick > body
    upper_wick = last["high"] - max(last["open"], last["close"])
    return upper_wick > body


def _compute_stop_loss_take_profit(df: pd.DataFrame, direction: str, lookback: int = 20):
    recent = df.tail(lookback)
    entry_price = df["close"].iloc[-1]

    if direction == "achat":
        stop_loss = recent["low"].min()
        risk = entry_price - stop_loss
        take_profit = entry_price + risk * config.RR_RATIO_MIN
    else:
        stop_loss = recent["high"].max()
        risk = stop_loss - entry_price
        take_profit = entry_price - risk * config.RR_RATIO_MIN

    if risk <= 0:
        return None, None, None

    rr_ratio = abs(take_profit - entry_price) / risk
    return stop_loss, take_profit, rr_ratio


def evaluate_entry(
    asset: str,
    timeframe: str,
    df_entry: pd.DataFrame,
    trend_direction: str,
    mode: str = "prudent",
) -> Optional[Signal]:
    if trend_direction == "neutre" and mode == "prudent":
        return None

    direction = "achat" if trend_direction == "haussier" else "vente"
    if mode == "scalping":
        direction = "achat" if df_entry["macd_hist"].iloc[-1] > 0 else "vente
