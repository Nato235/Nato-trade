"""
Récupération des données de marché depuis Twelve Data.

Fonctionnalités :
- Limitation globale des appels API.
- Maximum de 7 appels par fenêtre de 60 secondes.
- Minimum de 9 secondes entre deux appels.
- Cache partagé par symbole + timeframe.
- Réutilisation des données déjà téléchargées.
- Protection contre les erreurs 429.
- Reprise automatique après limitation API.
- Utilisation du cache en cas d'erreur réseau.
"""

import time
import logging
import threading
from collections import deque

import requests
import pandas as pd

from . import config


logger = logging.getLogger("nato_trade.data_fetch")


# ============================================================
# LIMITATION TWELVE DATA
# ============================================================

# Ton plan gratuit est indiqué comme étant à 8 requêtes/minute.
# On garde volontairement une marge de sécurité.
_MAX_CALLS_PER_MINUTE = 7

# Minimum entre deux requêtes.
_MIN_SECONDS_BETWEEN_CALLS = 9.0

_call_times = deque()
_rate_limit_lock = threading.Lock()

# Timestamp jusqu'auquel l'API est considérée comme temporairement bloquée.
_api_blocked_until = 0.0


# ============================================================
# CACHE
# ============================================================

_CACHE_TTL_SECONDS = 45

# IMPORTANT :
# La clé ne contient PAS output_size.
#
# Exemple :
# USD/JPY + 1h + 200
# puis
# USD/JPY + 1h + 80
#
# utilisent le même cache.
_cache = {}
_cache_lock = threading.Lock()


# ============================================================
# SESSION HTTP
# ============================================================

_session = requests.Session()


# ============================================================
# LIMITER
# ============================================================

def _wait_for_api_slot():
    """
    Attend jusqu'à ce qu'une nouvelle requête Twelve Data soit autorisée.
    """

    while True:

        with _rate_limit_lock:

            now = time.time()

            # ------------------------------------------------
            # Blocage après 429
            # ------------------------------------------------

            if now < _api_blocked_until:
                wait = _api_blocked_until - now
            else:
                wait = 0.0

            # ------------------------------------------------
            # Supprimer les appels vieux de plus de 60 secondes
            # ------------------------------------------------

            while _call_times and now - _call_times[0] >= 60:
                _call_times.popleft()

            # ------------------------------------------------
            # Maximum 7 appels / minute
            # ------------------------------------------------

            if wait <= 0 and len(_call_times) >= _MAX_CALLS_PER_MINUTE:

                wait = (
                    60
                    - (now - _call_times[0])
                    + 1.0
                )

            # ------------------------------------------------
            # Minimum entre deux appels
            # ------------------------------------------------

            if wait <= 0 and _call_times:

                elapsed = now - _call_times[-1]

                if elapsed < _MIN_SECONDS_BETWEEN_CALLS:

                    wait = (
                        _MIN_SECONDS_BETWEEN_CALLS
                        - elapsed
                    )

            # ------------------------------------------------
            # Slot disponible
            # ------------------------------------------------

            if wait <= 0:

                _call_times.append(time.time())

                return

        logger.warning(
            "Limiteur Twelve Data : attente %.1f secondes",
            wait,
        )

        time.sleep(max(wait, 0.5))


# ============================================================
# BLOCAGE API
# ============================================================

def _block_api(seconds: float):

    global _api_blocked_until

    with _rate_limit_lock:

        new_until = time.time() + seconds

        if new_until > _api_blocked_until:

            _api_blocked_until = new_until

    logger.warning(
        "Twelve Data temporairement bloqué pendant %.1f secondes",
        seconds,
    )


# ============================================================
# CACHE
# ============================================================

def _get_cached(
    symbol: str,
    interval: str,
    output_size: int,
):

    cache_key = (symbol, interval)

    with _cache_lock:

        cached = _cache.get(cache_key)

        if not cached:
            return None

        timestamp, df = cached

        age = time.time() - timestamp

        if age >= _CACHE_TTL_SECONDS:
            return None

        if len(df) < output_size:
            return None

        return df.tail(output_size).copy()


def _get_stale_cached(
    symbol: str,
    interval: str,
):

    """
    Retourne les données du cache même si elles sont expirées.

    Utile lorsqu'une requête Twelve Data échoue.
    """

    cache_key = (symbol, interval)

    with _cache_lock:

        cached = _cache.get(cache_key)

        if not cached:
            return None

        _, df = cached

        if df.empty:
            return None

        return df.copy()


def _save_cache(
    symbol: str,
    interval: str,
    df: pd.DataFrame,
):

    cache_key = (symbol, interval)

    with _cache_lock:

        _cache[cache_key] = (
            time.time(),
            df.copy(),
        )


# ============================================================
# FETCH CANDLES
# ============================================================

def fetch_candles(
    symbol: str,
    interval: str,
    output_size: int = 200,
) -> pd.DataFrame:

    output_size = max(
        1,
        min(int(output_size), 5000),
    )

    # ========================================================
    # 1. CACHE
    # ========================================================

    cached = _get_cached(
        symbol,
        interval,
        output_size,
    )

    if cached is not None:

        logger.debug(
            "Cache utilisé : %s/%s (%s bougies)",
            symbol,
            interval,
            output_size,
        )

        return cached

    # ========================================================
    # 2. LIMITEUR
    # ========================================================

    _wait_for_api_slot()

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": output_size,
        "apikey": config.TWELVE_DATA_API_KEY,
        "order": "ASC",
    }

    max_attempts = 3

    # ========================================================
    # 3. REQUÊTE
    # ========================================================

    for attempt in range(1, max_attempts + 1):

        try:

            response = _session.get(
                f"{config.TWELVE_DATA_BASE_URL}/time_series",
                params=params,
                timeout=15,
            )

            # =================================================
            # 429
            # =================================================

            if response.status_code == 429:

                retry_after = response.headers.get(
                    "Retry-After"
                )

                if retry_after:

                    try:
                        wait_seconds = float(retry_after)

                    except ValueError:
                        wait_seconds = 30.0

                else:

                    wait_seconds = 30.0 * attempt

                logger.warning(
                    "429 Twelve Data pour %s/%s "
                    "(tentative %s/%s). "
                    "Attente %.1f secondes.",
                    symbol,
                    interval,
                    attempt,
                    max_attempts,
                    wait_seconds,
                )

                _block_api(wait_seconds)

                if attempt < max_attempts:

                    time.sleep(wait_seconds)

                    _wait_for_api_slot()

                    continue

                # ------------------------------------------------
                # Après plusieurs 429 :
                # utiliser le cache expiré si disponible.
                # ------------------------------------------------

                fallback = _get_stale_cached(
                    symbol,
                    interval,
                )

                if fallback is not None:

                    logger.warning(
                        "429 persistant : utilisation des "
                        "anciennes données pour %s/%s",
                        symbol,
                        interval,
                    )

                    return fallback.tail(
                        output_size
                    ).copy()

                return pd.DataFrame()

            # =================================================
            # AUTRES ERREURS HTTP
            # =================================================

            response.raise_for_status()

            payload = response.json()

            # =================================================
            # CRÉDITS
            # =================================================

            credits_used = response.headers.get(
                "api-credits-used"
            )

            credits_left = response.headers.get(
                "api-credits-left"
            )

            if (
                credits_used is not None
                or credits_left is not None
            ):

                logger.info(
                    "Twelve Data crédits : "
                    "utilisés=%s, restants=%s",
                    credits_used,
                    credits_left,
                )

            # =================================================
            # ERREUR API
            # =================================================

            if payload.get("status") == "error":

                message = payload.get(
                    "message",
                    "Erreur inconnue Twelve Data",
                )

                logger.error(
                    "Erreur API Twelve Data pour %s/%s : %s",
                    symbol,
                    interval,
                    message,
                )

                fallback = _get_stale_cached(
                    symbol,
                    interval,
                )

                if fallback is not None:

                    logger.warning(
                        "Utilisation du cache après erreur API "
                        "pour %s/%s",
                        symbol,
                        interval,
                    )

                    return fallback.tail(
                        output_size
                    ).copy()

                return pd.DataFrame()

            # =================================================
            # VALEURS
            # =================================================

            values = payload.get(
                "values",
                [],
            )

            if not values:

                logger.warning(
                    "Aucune donnée reçue pour %s/%s",
                    symbol,
                    interval,
                )

                fallback = _get_stale_cached(
                    symbol,
                    interval,
                )

                if fallback is not None:

                    return fallback.tail(
                        output_size
                    ).copy()

                return pd.DataFrame()

            df = pd.DataFrame(values)

            # =================================================
            # DATETIME
            # =================================================

            if "datetime" not in df.columns:

                logger.error(
                    "Champ datetime absent pour %s/%s",
                    symbol,
                    interval,
                )

                return pd.DataFrame()

            df["datetime"] = pd.to_datetime(
                df["datetime"],
                errors="coerce",
            )

            # =================================================
            # OHLC
            # =================================================

            for col in (
                "open",
                "high",
                "low",
                "close",
            ):

                if col not in df.columns:

                    logger.error(
                        "Colonne %s absente pour %s/%s",
                        col,
                        symbol,
                        interval,
                    )

                    return pd.DataFrame()

                df[col] = pd.to_numeric(
                    df[col],
                    errors="coerce",
                )

            # =================================================
            # VOLUME
            # =================================================

            if "volume" in df.columns:

                df["volume"] = pd.to_numeric(
                    df["volume"],
                    errors="coerce",
                )

            # =================================================
            # NETTOYAGE
            # =================================================

            df = df.dropna(
                subset=[
                    "datetime",
                    "open",
                    "high",
                    "low",
                    "close",
                ]
            )

            df = (
                df
                .sort_values("datetime")
                .drop_duplicates(
                    subset=["datetime"],
                    keep="last",
                )
                .reset_index(drop=True)
            )

            if df.empty:

                logger.warning(
                    "DataFrame vide après nettoyage "
                    "pour %s/%s",
                    symbol,
                    interval,
                )

                return pd.DataFrame()

            # =================================================
            # CACHE
            # =================================================

            _save_cache(
                symbol,
                interval,
                df,
            )

            logger.debug(
                "Données récupérées : %s/%s (%s bougies)",
                symbol,
                interval,
                len(df),
            )

            return df.tail(
                output_size
            ).copy()

        # =====================================================
        # TIMEOUT
        # =====================================================

        except requests.Timeout:

            logger.warning(
                "Timeout Twelve Data pour %s/%s "
                "(tentative %s/%s)",
                symbol,
                interval,
                attempt,
                max_attempts,
            )

            if attempt < max_attempts:

                wait_seconds = 5 * attempt

                time.sleep(wait_seconds)

                _wait_for_api_slot()

                continue

            fallback = _get_stale_cached(
                symbol,
                interval,
            )

            if fallback is not None:

                logger.warning(
                    "Timeout : utilisation du cache "
                    "pour %s/%s",
                    symbol,
                    interval,
                )

                return fallback.tail(
                    output_size
                ).copy()

            return pd.DataFrame()

        # =====================================================
        # ERREUR RÉSEAU
        # =====================================================

        except requests.RequestException as exc:

            logger.error(
                "Erreur réseau Twelve Data pour %s/%s : %s",
                symbol,
                interval,
                exc,
            )

            fallback = _get_stale_cached(
                symbol,
                interval,
            )

            if fallback is not None:

                logger.warning(
                    "Erreur réseau : utilisation du cache "
                    "pour %s/%s",
                    symbol,
                    interval,
                )

                return fallback.tail(
                    output_size
                ).copy()

            return pd.DataFrame()

        # =====================================================
        # JSON INVALIDE
        # =====================================================

        except ValueError as exc:

            logger.error(
                "Erreur JSON Twelve Data pour %s/%s : %s",
                symbol,
                interval,
                exc,
            )

            return pd.DataFrame()

    return pd.DataFrame()
