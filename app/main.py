"""
Point d'entrée du moteur Nato Trade.

Le moteur :
- analyse H1 et M30 pour la tendance ;
- analyse les timeframes d'entrée ;
- évite les téléchargements doublons ;
- utilise le cache de data_fetch ;
- respecte les limites Twelve Data ;
- continue automatiquement après une limitation API.
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


logger = logging.getLogger(
    "nato_trade.main"
)


# ============================================================
# ANALYSE D'UN ACTIF
# ============================================================

def analyze_asset(asset: str):

    logger.info(
        "Analyse de %s",
        asset,
    )

    # ========================================================
    # H1
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
    # M30
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
    # INDICATEURS
    # ========================================================

    df_h1 = indicators.add_trend_indicators(
        df_h1
    )

    df_m30 = indicators.add_trend_indicators(
        df_m30
    )

    trend_h1 = (
        indicators.get_trend_direction(
            df_h1
        )
    )

    trend_m30 = (
        indicators.get_trend_direction(
            df_m30
        )
    )

    database.log_trend_analysis(
        asset,
        f"H1:{trend_h1}/M30:{trend_m30}",
    )

    # ========================================================
    # ALIGNEMENT
    # ========================================================

    if (
        trend_h1 != trend_m30
        or trend_h1 == "neutre"
    ):

        trend_direction = "neutre"

        logger.info(
            "%s : tendance non alignée "
            "(H1=%s, M30=%s)",
            asset,
            trend_h1,
            trend_m30,
        )

    else:

        trend_direction = trend_h1

        logger.info(
            "%s : tendance = %s",
            asset,
            trend_direction,
        )

    # ========================================================
    # TIMEFRAMES
    # ========================================================

    timeframes_to_fetch = []

    if trend_direction != "neutre":

        for timeframe in (
            config.TIMEFRAMES_ENTRY
        ):

            if timeframe not in timeframes_to_fetch:

                timeframes_to_fetch.append(
                    timeframe
                )

    if config.SCALPING_ENABLED:

        for timeframe in (
            config.SCALPING_TIMEFRAMES
        ):

            if timeframe not in timeframes_to_fetch:

                timeframes_to_fetch.append(
                    timeframe
                )

    # ========================================================
    # CACHE / RÉCUPÉRATION UNIQUE
    # ========================================================

    candles_by_timeframe = {}

    for timeframe in timeframes_to_fetch:

        df = data_fetch.fetch_candles(
            asset,
            timeframe,
            output_size=200,
        )

        if df.empty:

            logger.warning(
                "Données absentes %s/%s",
                asset,
                timeframe,
            )

            continue

        candles_by_timeframe[
            timeframe
        ] = df

    # ========================================================
    # MODE PRUDENT
    # ========================================================

    if trend_direction != "neutre":

        for timeframe in (
            config.TIMEFRAMES_ENTRY
        ):

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
                    "SIGNAL PRUDENT : %s %s %s",
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
    # SCALPING
    # ========================================================

    if config.SCALPING_ENABLED:

        for timeframe in (
            config.SCALPING_TIMEFRAMES
        ):

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
                    "SIGNAL SCALPING : %s %s %s",
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
# BOUCLE PRINCIPALE
# ============================================================

def run_forever():

    database.init_db()

    logger.info(
        "Nato Trade démarré. Actifs suivis : %s",
        ", ".join(config.ASSETS),
    )

    while True:

        try:

            forex_active = (
                schedule.is_forex_active()
            )

            if not forex_active:

                logger.info(
                    "Forex hors horaires : pause."
                )

            for asset in config.ASSETS:

                if (
                    asset in config.FOREX_ASSETS
                    and not forex_active
                ):

                    continue

                try:

                    analyze_asset(
                        asset
                    )

                except Exception:

                    logger.exception(
                        "Erreur analyse %s",
                        asset,
                    )

            # =================================================
            # PAUSE ENTRE LES CYCLES
            # =================================================

            # On force une pause raisonnable.
            # Le cache empêche les appels inutiles.
            poll_interval = max(
                int(
                    getattr(
                        config,
                        "POLL_INTERVAL_ENTRY",
                        300,
                    )
                ),
                300,
            )

            logger.info(
                "Prochain cycle dans %s secondes.",
                poll_interval,
            )

            time.sleep(
                poll_interval
            )

        except Exception:

            logger.exception(
                "Erreur dans la boucle principale"
            )

            time.sleep(30)


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":

    run_forever()
