"""
Détection simplifiée de figures chartistes (structure de prix).
Critère optionnel de la règle de confirmation "2 sur 4" : sa présence renforce
un signal mais son absence ne bloque jamais un signal déjà validé par 2 autres
critères (RSI, MACD, structure classique).
"""

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


def _find_swing_points(df: pd.DataFrame, order: int = 5):
    """Repère les sommets et creux locaux (swing highs/lows)."""
    highs_idx = argrelextrema(df["high"].values, np.greater_equal, order=order)[0]
    lows_idx = argrelextrema(df["low"].values, np.less_equal, order=order)[0]
    return highs_idx, lows_idx


def detect_double_top(df: pd.DataFrame, tolerance: float = 0.002) -> bool:
    """Détecte un double sommet approximatif sur les dernières bougies."""
    highs_idx, _ = _find_swing_points(df)
    if len(highs_idx) < 2:
        return False

    last_two = highs_idx[-2:]
    price_a = df["high"].iloc[last_two[0]]
    price_b = df["high"].iloc[last_two[1]]

    return abs(price_a - price_b) / price_a < tolerance


def detect_double_bottom(df: pd.DataFrame, tolerance: float = 0.002) -> bool:
    """Détecte un double creux approximatif sur les dernières bougies."""
    _, lows_idx = _find_swing_points(df)
    if len(lows_idx) < 2:
        return False

    last_two = lows_idx[-2:]
    price_a = df["low"].iloc[last_two[0]]
    price_b = df["low"].iloc[last_two[1]]

    return abs(price_a - price_b) / price_a < tolerance


def detect_triangle(df: pd.DataFrame, lookback: int = 30):
    """
    Détecte une convergence de type triangle sur les `lookback` dernières bougies.
    Retourne "ascendant", "descendant", "symetrique" ou None.
    """
    recent = df.tail(lookback)
    if len(recent) < lookback:
        return None

    highs_idx, lows_idx = _find_swing_points(recent, order=3)
    if len(highs_idx) < 2 or len(lows_idx) < 2:
        return None

    high_slope = np.polyfit(highs_idx, recent["high"].iloc[highs_idx], 1)[0]
    low_slope = np.polyfit(lows_idx, recent["low"].iloc[lows_idx], 1)[0]

    flat_threshold = recent["close"].mean() * 0.0005

    high_flat = abs(high_slope) < flat_threshold
    low_flat = abs(low_slope) < flat_threshold

    if high_flat and low_slope > 0:
        return "ascendant"
    if low_flat and high_slope < 0:
        return "descendant"
    if high_slope < 0 and low_slope > 0:
        return "symetrique"
    return None


def detect_chart_pattern(df: pd.DataFrame):
    """
    Point d'entrée unique du module : renvoie le nom de la figure détectée,
    ou None si rien de fiable n'est détecté.
    """
    if detect_double_top(df):
        return "double_sommet"
    if detect_double_bottom(df):
        return "double_creux"

    triangle = detect_triangle(df)
    if triangle:
        return f"triangle_{triangle}"

    return None
