"""
Récupération des données de marché depuis Twelve Data.

Protection renforcée contre les limites API :
- maximum 7 appels par fenêtre de 60 secondes ;
- minimum 9 secondes entre deux appels ;
- blocage global après limitation Twelve Data ;
- cache partagé par symbole + timeframe ;
- utilisation du cache pendant une limitation ;
- reprise automatique après expiration du blocage ;
- aucune nouvelle requête inutile pendant un blocage.
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

_MAX_CALLS_PER_MINUTE = 7
_MIN_SECONDS_BETWEEN_CALLS = 9.0

_call_times = deque()
_rate_limit_lock = threading.Lock()

# Timestamp jusqu'auquel Twelve Data est considéré comme bloqué.
_api_blocked_until = 0.0


# ============================================================
# CACHE
# ============================================================

# Cache frais pendant 5 minutes.
_CACHE_TTL_SECONDS = 300

_cache = {}
_cache_lock = threading.Lock()


# ============================================================
# SESSION HTTP
# ============================================================

_session = requests.Session()


# ============================================================
# VÉRIFICATION DU BLOCAGE
# ============================================================

def _is_api_blocked():

    with _rate_limit_lock:

        return time.time() < _api_blocked_until


def _get_block_remaining():

    with _rate_limit_lock:

        remaining = _api_blocked_until - time.time()

        return max(
            0.0,
            remaining,
        )


# ============================================================
# LIMITEUR
# ============================================================

def _wait_for_api_slot():

    while True:

        with _rate_limit_lock:

            now = time.time()

            # ------------------------------------------------
            # Blocage global
            # ------------------------------------------------

            if now < _api_blocked_until:

                wait = (
                    _api_blocked_until
                    - now
                )

            else:

                wait = 0.0

            # ------------------------------------------------
            # Supprimer les appels vieux de 60 secondes
            # ------------------------------------------------

            while (
                _call_times
                and now - _call_times[0] >= 60
            ):

                _call_times.popleft()

            # ------------------------------------------------
            # Maximum 7 appels/minute
            # ------------------------------------------------

            if (
                wait <= 0
                and len(_call_times)
                >= _MAX_CALLS_PER_MINUTE
            ):

                wait = (
                    60
                    - (now - _call_times[0])
                    + 1.0
                )

            # ------------------------------------------------
            # Minimum entre deux appels
            # ------------------------------------------------

            if (
                wait <= 0
                and _call_times
            ):

                elapsed = (
                    now
                    - _call_times[-1]
                )

                if (
                    elapsed
                    < _MIN_SECONDS_BETWEEN_CALLS
                ):

                    wait = (
                        _MIN_SECONDS_BETWEEN_CALLS
                        - elapsed
                    )

            # ------------------------------------------------
            # Slot disponible
            # ------------------------------------------------

            if wait <= 0:

                _call_times.append(
                    time.time()
                )

                return True

        logger.info(
            "Twelve Data limité : attente %.1f secondes",
            wait,
        )

        time.sleep(
            min(
                max(wait, 0.5),
                10.0,
            )
        )


# ============================================================
# BLOCAGE API
# ============================================================

def _block_api(seconds: float):

    global _api_blocked_until

    with _rate_limit_lock:

        new_until = (
            time.time()
            + seconds
        )

        if (
            new_until
            > _api_blocked_until
        ):

            _api_blocked_until = (
                new_until
            )

    logger.warning(
        "Twelve Data temporairement bloqué pendant %.1f secondes",
        seconds,
    )


# ============================================================
# CACHE FRAIS
# ============================================================

def _get_cached(
    symbol: str,
    interval: str,
    output_size: int,
):

    cache_key = (
        symbol,
        interval,
    )

    with _cache_lock:

        cached = _cache.get(
            cache_key
        )

        if not cached:
            return None

        timestamp, df = cached

        age = (
            time.time()
            - timestamp
        )

        if age >= _CACHE_TTL_SECONDS:

            return None

        if len(df) < output_size:

            return None

        logger.debug(
            "Cache frais utilisé : %s/%s",
            symbol,
            interval,
        )

        return (
            df
            .tail(output_size)
            .copy()
        )


# ============================================================
# CACHE EXPIRÉ
# ============================================================

def _get_stale_cached(
    symbol: str,
    interval: str,
    output_size: int = 200,
):

    cache_key = (
        symbol,
        interval,
    )

    with _cache_lock:

        cached = _cache.get(
            cache_key
        )

        if not cached:

            return None

        _, df = cached

        if df.empty:

            return None

        logger.debug(
            "Cache expiré utilisé : %s/%s",
            symbol,
            interval,
        )

        return (
            df
            .tail(output_size)
            .copy()
        )


# ============================================================
# SAUVEGARDE CACHE
# ============================================================

def _save_cache(
    symbol: str,
    interval: str,
    df: pd.DataFrame,
):

    cache_key = (
        symbol,
        interval,
    )

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
        min(
            int(output_size),
            5000,
        ),
    )

    # ========================================================
    # 1. CACHE FRAIS
    # ========================================================

    cached = _get_cached(
        symbol,
        interval,
        output_size,
    )

    if cached is not None:

        return cached

    # ========================================================
    # 2. SI API BLOQUÉE
    # ========================================================

    if _is_api_blocked():

        remaining = (
            _get_block_remaining()
        )

        logger.warning(
            "Twelve Data encore bloqué "
            "(%.1f secondes restantes) "
            "pour %s/%s",
            remaining,
            symbol,
            interval,
        )

        # Utiliser le cache expiré.
        fallback = _get_stale_cached(
            symbol,
            interval,
            output_size,
        )

        if fallback is not None:

            return fallback

        # IMPORTANT :
        # On ne fait PAS de nouvelle requête.
        return pd.DataFrame()

    # ========================================================
    # 3. OBTENIR UN SLOT API
    # ========================================================

    _wait_for_api_slot()

    # ========================================================
    # 4. PARAMÈTRES
    # ========================================================

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": output_size,
        "apikey": config.TWELVE_DATA_API_KEY,
        "order": "ASC",
    }

    max_attempts = 2

    # ========================================================
    # 5. REQUÊTE
    # ========================================================

    for attempt in range(
        1,
        max_attempts + 1,
    ):

        try:

            response = _session.get(
                (
                    f"{config.TWELVE_DATA_BASE_URL}"
                    "/time_series"
                ),
                params=params,
                timeout=15,
            )

            # =================================================
            # 429
            # =================================================

            if response.status_code == 429:

                retry_after = (
                    response.headers.get(
                        "Retry-After"
                    )
                )

                if retry_after:

                    try:

                        wait_seconds = float(
                            retry_after
                        )

                    except ValueError:

                        wait_seconds = 60.0

                else:

                    wait_seconds = 60.0

                _block_api(
                    wait_seconds
                )

                logger.warning(
                    "Twelve Data 429 pour %s/%s. "
                    "Aucune nouvelle requête "
                    "pendant %.1f secondes.",
                    symbol,
                    interval,
                    wait_seconds,
                )

                fallback = _get_stale_cached(
                    symbol,
                    interval,
                    output_size,
                )

                if fallback is not None:

                    return fallback

                return pd.DataFrame()

            # =================================================
            # AUTRES ERREURS HTTP
            # =================================================

            response.raise_for_status()

            payload = response.json()

            # =================================================
            # CRÉDITS
            # =================================================

            credits_used = (
                response.headers.get(
                    "api-credits-used"
                )
            )

            credits_left = (
                response.headers.get(
                    "api-credits-left"
                )
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

            if (
                payload.get("status")
                == "error"
            ):

                message = payload.get(
                    "message",
                    "Erreur inconnue Twelve Data",
                )

                logger.error(
                    "Erreur API Twelve Data "
                    "pour %s/%s : %s",
                    symbol,
                    interval,
                    message,
                )

                fallback = (
                    _get_stale_cached(
                        symbol,
                        interval,
                        output_size,
                    )
                )

                if fallback is not None:

                    return fallback

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
                    "Aucune donnée reçue "
                    "pour %s/%s",
                    symbol,
                    interval,
                )

                fallback = (
                    _get_stale_cached(
                        symbol,
                        interval,
                        output_size,
                    )
                )

                if fallback is not None:

                    return fallback

                return pd.DataFrame()

            # =================================================
            # DATAFRAME
            # =================================================

            df = pd.DataFrame(
                values
            )

            # =================================================
            # DATETIME
            # =================================================

            if "datetime" not in df.columns:

                logger.error(
                    "Champ datetime absent "
                    "pour %s/%s",
                    symbol,
                    interval,
                )

                return pd.DataFrame()

            df["datetime"] = (
                pd.to_datetime(
                    df["datetime"],
                    errors="coerce",
                )
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

                if (
                    col
                    not in df.columns
                ):

                    logger.error(
                        "Colonne %s absente "
                        "pour %s/%s",
                        col,
                        symbol,
                        interval,
                    )

                    return pd.DataFrame()

                df[col] = (
                    pd.to_numeric(
                        df[col],
                        errors="coerce",
                    )
                )

            # =================================================
            # VOLUME
            # =================================================

            if "volume" in df.columns:

                df["volume"] = (
                    pd.to_numeric(
                        df["volume"],
                        errors="coerce",
                    )
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
                .sort_values(
                    "datetime"
                )
                .drop_duplicates(
                    subset=[
                        "datetime"
                    ],
                    keep="last",
                )
                .reset_index(
                    drop=True
                )
            )

            if df.empty:

                return pd.DataFrame()

            # =================================================
            # CACHE
            # =================================================

            _save_cache(
                symbol,
                interval,
                df,
            )

            logger.info(
                "Données récupérées : "
                "%s/%s (%s bougies)",
                symbol,
                interval,
                len(df),
            )

            return (
                df
                .tail(output_size)
                .copy()
            )

        # =====================================================
        # TIMEOUT
        # =====================================================

        except requests.Timeout:

            logger.warning(
                "Timeout Twelve Data "
                "pour %s/%s",
                symbol,
                interval,
            )

            fallback = (
                _get_stale_cached(
                    symbol,
                    interval,
                    output_size,
                )
            )

            if fallback is not None:

                return fallback

            return pd.DataFrame()

        # =====================================================
        # ERREUR RÉSEAU
        # =====================================================

        except requests.RequestException as exc:

            logger.error(
                "Erreur réseau Twelve Data "
                "pour %s/%s : %s",
                symbol,
                interval,
                exc,
            )

            fallback = (
                _get_stale_cached(
                    symbol,
                    interval,
                    output_size,
                )
            )

            if fallback is not None:

                return fallback

            return pd.DataFrame()

        # =====================================================
        # JSON INVALIDE
        # =====================================================

        except ValueError as exc:

            logger.error(
                "Erreur JSON Twelve Data "
                "pour %s/%s : %s",
                symbol,
                interval,
                exc,
            )

            return pd.DataFrame()

    return pd.DataFrame()
