"""
Point d'entrée du moteur Nato Trade.

Version optimisée pour limiter les appels Twelve Data.

Objectifs :
- éviter les appels inutiles ;
- analyser les actifs progressivement ;
- ne pas relancer immédiatement une analyse après une limitation API ;
- conserver l'analyse H1/M30 ;
- récupérer chaque timeframe une seule fois par actif ;
- laisser data_fetch.py gérer le rate-limit Twelve Data.
"""

import logging
import time

from . import (
    config,
    data_fetch,
    indicators,
    signals,
    notify,
    database,
    schedule,
)


logger = logging.getLogger("nato_trade.main")


# ============================================================
# PARAMÈTRES DE SÉCURITÉ API
# ============================================================

ASSET_COOLDOWN_SECONDS = 120

PAUSE_BETWEEN_ASSETS = 10

_last_analysis = {}


# ============================================================
# ANALYSE D'UN ACTIF
# ============================================================

def analyze_asset(asset: str):

    now = time.time()

    last_time = _last_analysis.get(asset, 0)

    if now - last_time < ASSET_COOLDOWN_SECONDS:

        logger.info(
            "%s : cooldown actif, analyse ignorée.",
            asset,
        )

        return

    _last_analysis[asset] = now

    logger.info(
        "Analyse de %s",
        asset,
    )

    # ========================================================
    # 1. TENDANCE H1
    # ========================================================

    df_h1 = data_fetch.fetch_candles(
        asset,
        "1h",
        output_size=200,
    )

    if df_h1.empty:

        logger.warning(
            "Données H1 manquantes pour %s",
            asset,
        )

        return

    # ========================================================
    # 2. TENDANCE M30
    # ========================================================

    df_m30 = data_fetch.fetch_candles(
        asset,
        "30min",
        output_size=200,
    )

    if df_m30.empty:

        logger.warning(
            "Données M30 manquantes pour %s",
            asset,
        )

        return

    # ========================================================
    # 3. INDICATEURS DE TENDANCE
    # ========================================================

    df_h1 = indicators.add_trend_indicators(
        df_h1
    )

    df_m30 = indicators.add_trend_indicators(
        df_m30
    )

    trend_h1 = indicators.get_trend_direction(
        df_h1
    )

    trend_m30 = indicators.get_trend_direction(
        df_m30
    )

    database.log_trend_analysis(
        asset,
        f"H1:{trend_h1}/M30:{trend_m30}",
    )

    logger.info(
        "%s : H1=%s | M30=%s",
        asset,
        trend_h1,
        trend_m30,
    )

    # ========================================================
    # 4. ALIGNEMENT H1 / M30
    # ========================================================

    if (
        trend_h1 != trend_m30
        or trend_h1 == "neutre"
    ):

        trend_direction = "neutre"

        logger.info(
            "%s : pas de tendance claire alignée.",
            asset,
        )

    else:

        trend_direction = trend_h1

        logger.info(
            "%s : tendance de fond = %s",
            asset,
            trend_direction,
        )

    # ========================================================
    # 5. TIMEFRAMES À RÉCUPÉRER
    # ========================================================

    timeframes_to_fetch = []

    if trend_direction != "neutre":

        for timeframe in config.TIMEFRAMES_ENTRY:

            if timeframe not in timeframes_to_fetch:

                timeframes_to_fetch.append(
                    timeframe
                )

    if config.SCALPING_ENABLED:

        for timeframe in config.SCALPING_TIMEFRAMES:

            if timeframe not in timeframes_to_fetch:

                timeframes_to_fetch.append(
                    timeframe
                )

    # ========================================================
    # 6. RÉCUPÉRATION UNIQUE
    # ========================================================

    candles_by_timeframe = {}

    for timeframe in timeframes_to_fetch:

        logger.info(
            "Récupération %s/%s",
            asset,
            timeframe,
        )

        df = data_fetch.fetch_candles(
            asset,
            timeframe,
            output_size=200,
        )

        if df.empty:

            logger.warning(
                "Données manquantes pour %s/%s",
                asset,
                timeframe,
            )

            continue

        candles_by_timeframe[
            timeframe
        ] = df

    # ========================================================
    # 7. MODE PRUDENT
    # ========================================================

    if trend_direction != "neutre":

        for timeframe in config.TIMEFRAMES_ENTRY:

            df_entry = (
                candles_by_timeframe.get(
                    timeframe
                )
            )

            if df_entry is None:

                continue

            signal = signals.evaluate_entry(
                asset,
                timeframe,
                df_entry,
                trend_direction,
                mode="prudent",
            )

            if signal:

                logger.info(
                    "SIGNAL PRUDENT détecté : "
                    "%s %s %s",
                    asset,
                    timeframe,
                    signal.direction,
                )

                database.save_signal(
                    signal
                )

                notify.send_signal_notification(
                    signal
                )

    # ========================================================
    # 8. MODE SCALPING
    # ========================================================

    if config.SCALPING_ENABLED:

        for timeframe in config.SCALPING_TIMEFRAMES:

            df_scalp = (
                candles_by_timeframe.get(
                    timeframe
                )
            )

            if df_scalp is None:

                continue

            signal = signals.evaluate_entry(
                asset,
                timeframe,
                df_scalp,
                trend_direction,
                mode="scalping",
            )

            if signal:

                logger.info(
                    "SIGNAL SCALPING détecté : "
                    "%s %s %s",
                    asset,
                    timeframe,
                    signal.direction,
                )

                database.save_signal(
                    signal
                )

                notify.send_signal_notification(
                    signal
                )


# ============================================================
# ANALYSE PROGRESSIVE DES ACTIFS
# ============================================================

def analyze_assets_progressively():

    assets = list(
        config.ASSETS
    )

    logger.info(
        "Début du cycle : %s actif(s)",
        len(assets),
    )

    for index, asset in enumerate(
        assets,
        start=1,
    ):

        logger.info(
            "Actif %s/%s : %s",
            index,
            len(assets),
            asset,
        )

        try:

            analyze_asset(
                asset
            )

        except Exception:

            logger.exception(
                "Erreur inattendue lors "
                "de l'analyse de %s",
                asset,
            )

        if index < len(assets):

            logger.info(
                "Pause de %s secondes avant le prochain actif.",
                PAUSE_BETWEEN_ASSETS,
            )

            time.sleep(
                PAUSE_BETWEEN_ASSETS
            )


# ============================================================
# BOUCLE PRINCIPALE
# ============================================================

def run_forever():

    database.init_db()

    logger.info(
        "Nato Trade démarré. "
        "Actifs suivis: %s",
        ", ".join(config.ASSETS),
    )

    while True:

        try:

            forex_active = (
                schedule.is_forex_active()
            )

            if not forex_active:

                logger.info(
                    "Hors horaires forex "
                    "(Lun-Ven 8h-21h) : "
                    "forex mis en pause, "
                    "crypto continue."
                )

            # ------------------------------------------------
            # Construction de la liste active
            # ------------------------------------------------

            active_assets = []

            for asset in config.ASSETS:

                if (
                    asset in config.FOREX_ASSETS
                    and not forex_active
                ):

                    continue

                active_assets.append(
                    asset
                )

            # ------------------------------------------------
            # Analyse progressive
            # ------------------------------------------------

            for index, asset in enumerate(
                active_assets,
                start=1,
            ):

                logger.info(
                    "Analyse %s/%s : %s",
                    index,
                    len(active_assets),
                    asset,
                )

                try:

                    analyze_asset(
                        asset
                    )

                except Exception:

                    logger.exception(
                        "Erreur inattendue lors "
                        "de l'analyse de %s",
                        asset,
                    )

                if index < len(active_assets):

                    time.sleep(
                        PAUSE_BETWEEN_ASSETS
                    )

            # ------------------------------------------------
            # Pause entre les cycles complets
            # ------------------------------------------------

            # Minimum 1 heure entre deux cycles.
            # Cela protège le quota Twelve Data.

            poll_interval = max(
                int(
                    getattr(
                        config,
                        "POLL_INTERVAL_ENTRY",
                        3600,
                    )
                ),
                3600,
            )

            logger.info(
                "Cycle terminé. "
                "Prochaine analyse dans %s secondes.",
                poll_interval,
            )

            time.sleep(
                poll_interval
            )

        except Exception:

            logger.exception(
                "Erreur inattendue dans "
                "la boucle principale."
            )

            time.sleep(
                60
            )


# ============================================================
# LANCEMENT DIRECT
# ============================================================

if __name__ == "__main__":

    run_forever()
