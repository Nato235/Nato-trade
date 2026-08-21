"""
Récupération optimisée des données Twelve Data.

Objectifs :
- maximum 7 appels par fenêtre de 60 secondes ;
- minimum 9 secondes entre deux appels ;
- cache intelligent ;
- utilisation du cache expiré en cas de blocage/erreur ;
- reprise automatique après limitation ;
- aucune boucle agressive contre Twelve Data.
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
# LIMITES TWELVE DATA
# ============================================================

_MAX_CALLS_PER_MINUTE = 7
_MIN_SECONDS_BETWEEN_CALLS = 9.0

_call_times = deque()
_rate_limit_lock = threading.Lock()

_api_blocked_until = 0.0


# ============================================================
# CACHE
# ============================================================

# On garde les données plusieurs minutes.
# Les bougies anciennes restent utilisables si Twelve Data
# est temporairement indisponible.
_CACHE_TTL_SECONDS = 180

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

    while True:

        with _rate_limit_lock:

            now = time.time()

            # ------------------------------------------------
            # Blocage Twelve Data
            # ------------------------------------------------

            if now < _api_blocked_until:

                wait = _api_blocked_until - now

            else:

                wait = 0.0

            # ------------------------------------------------
            # Nettoyage des anciens appels
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
                    + 1
                )

            # ------------------------------------------------
            # Minimum 9 secondes entre appels
            # ------------------------------------------------

            if (
                wait <= 0
                and _call_times
            ):

                elapsed = (
                    now
                    - _call_times[-1]
                )

                if elapsed < _MIN_SECONDS_BETWEEN_CALLS:

                    wait = (
                        _MIN_SECONDS_BETWEEN_CALLS
                        - elapsed
                    )

            # ------------------------------------------------
            # Autorisé
            # ------------------------------------------------

            if wait <= 0:

                _call_times.append(
                    time.time()
                )

                return

        logger.warning(
            "Twelve Data limité : attente %.1f secondes",
            wait,
        )

        time.sleep(
            max(wait, 0.5)
        )


# ============================================================
# BLOCAGE API
# ============================================================

def _block_api(seconds):

    global _api_blocked_until

    with _rate_limit_lock:

        until = (
            time.time()
            + float(seconds)
        )

        if until > _api_blocked_until:

            _api_blocked_until = until

    logger.warning(
        "Twelve Data temporairement bloqué pendant %.1f secondes",
        seconds,
    )


# ============================================================
# CACHE
# ============================================================

def _get_cached(
    symbol,
    interval,
    output_size,
):

    key = (
        symbol,
        interval,
    )

    with _cache_lock:

        item = _cache.get(key)

        if item is None:
            return None

        timestamp, df = item

        age = (
            time.time()
            - timestamp
        )

        if age > _CACHE_TTL_SECONDS:

            return None

        if len(df) < output_size:

            return None

        return df.tail(
            output_size
        ).copy()


def _get_stale_cached(
    symbol,
    interval,
    output_size,
):

    key = (
        symbol,
        interval,
    )

    with _cache_lock:

        item = _cache.get(key)

        if item is None:
            return None

        _, df = item

        if df.empty:
            return None

        return df.tail(
            output_size
        ).copy()


def _save_cache(
    symbol,
    interval,
    df,
):

    key = (
        symbol,
        interval,
    )

    with _cache_lock:

        _cache[key] = (
            time.time(),
            df.copy(),
        )


# ============================================================
# FETCH
# ============================================================

def fetch_candles(
    symbol,
    interval,
    output_size=200,
):

    output_size = max(
        1,
        min(
            int(output_size),
            5000,
        ),
    )

    # ========================================================
    # CACHE VALIDE
    # ========================================================

    cached = _get_cached(
        symbol,
        interval,
        output_size,
    )

    if cached is not None:

        logger.debug(
            "Cache utilisé : %s/%s",
            symbol,
            interval,
        )

        return cached

    # ========================================================
    # PROTECTION GLOBALE
    # ========================================================

    _wait_for_api_slot()

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": output_size,
        "apikey": config.TWELVE_DATA_API_KEY,
        "order": "ASC",
    }

    try:

        response = _session.get(
            f"{config.TWELVE_DATA_BASE_URL}/time_series",
            params=params,
            timeout=15,
        )

        # ====================================================
        # RATE LIMIT
        # ====================================================

        if response.status_code == 429:

            retry_after = (
                response.headers.get(
                    "Retry-After"
                )
            )

            try:

                wait_seconds = (
                    float(retry_after)
                    if retry_after
                    else 60.0
                )

            except ValueError:

                wait_seconds = 60.0

            _block_api(
                wait_seconds
            )

            fallback = _get_stale_cached(
                symbol,
                interval,
                output_size,
            )

            if fallback is not None:

                logger.warning(
                    "429 : utilisation du cache "
                    "pour %s/%s",
                    symbol,
                    interval,
                )

                return fallback

            return pd.DataFrame()

        # ====================================================
        # AUTRES ERREURS HTTP
        # ====================================================

        response.raise_for_status()

        payload = response.json()

        # ====================================================
        # ERREUR TWELVE DATA
        # ====================================================

        if payload.get("status") == "error":

            message = payload.get(
                "message",
                "Erreur Twelve Data",
            )

            logger.warning(
                "Erreur Twelve Data %s/%s : %s",
                symbol,
                interval,
                message,
            )

            fallback = _get_stale_cached(
                symbol,
                interval,
                output_size,
            )

            if fallback is not None:

                return fallback

            return pd.DataFrame()

        # ====================================================
        # DONNÉES
        # ====================================================

        values = payload.get(
            "values",
            [],
        )

        if not values:

            logger.warning(
                "Aucune donnée : %s/%s",
                symbol,
                interval,
            )

            fallback = _get_stale_cached(
                symbol,
                interval,
                output_size,
            )

            if fallback is not None:

                return fallback

            return pd.DataFrame()

        df = pd.DataFrame(
            values
        )

        # ====================================================
        # DATETIME
        # ====================================================

        if "datetime" not in df.columns:

            return pd.DataFrame()

        df["datetime"] = pd.to_datetime(
            df["datetime"],
            errors="coerce",
        )

        # ====================================================
        # OHLC
        # ====================================================

        for column in (
            "open",
            "high",
            "low",
            "close",
        ):

            if column not in df.columns:

                return pd.DataFrame()

            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            )

        # ====================================================
        # VOLUME
        # ====================================================

        if "volume" in df.columns:

            df["volume"] = pd.to_numeric(
                df["volume"],
                errors="coerce",
            )

        # ====================================================
        # NETTOYAGE
        # ====================================================

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

            return pd.DataFrame()

        # ====================================================
        # CACHE
        # ====================================================

        _save_cache(
            symbol,
            interval,
            df,
        )

        logger.info(
            "Données récupérées : %s/%s (%s bougies)",
            symbol,
            interval,
            len(df),
        )

        return df.tail(
            output_size
        ).copy()

    # ========================================================
    # TIMEOUT
    # ========================================================

    except requests.Timeout:

        logger.warning(
            "Timeout Twelve Data : %s/%s",
            symbol,
            interval,
        )

        fallback = _get_stale_cached(
            symbol,
            interval,
            output_size,
        )

        if fallback is not None:

            return fallback

        return pd.DataFrame()

    # ========================================================
    # ERREUR RÉSEAU
    # ========================================================

    except requests.RequestException as exc:

        logger.warning(
            "Erreur réseau Twelve Data : %s",
            exc,
        )

        fallback = _get_stale_cached(
            symbol,
            interval,
            output_size,
        )

        if fallback is not None:

            return fallback

        return pd.DataFrame()

    # ========================================================
    # JSON
    # ========================================================

    except ValueError as exc:

        logger.warning(
            "JSON Twelve Data invalide : %s",
            exc,
        )

        fallback = _get_stale_cached(
            symbol,
            interval,
            output_size,
        )

        if fallback is not None:

            return fallback

        return pd.DataFrame()
