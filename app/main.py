"""
Point d'entrée du moteur Nato Trade.

Le moteur :
- analyse H1 et M30 pour déterminer la tendance ;
- analyse M15/M5/M1 pour rechercher les entrées ;
- évite les téléchargements doublons ;
- évite de récupérer deux fois M5/M1 lorsque le scalping
  et le mode prudent utilisent le même timeframe ;
- envoie une notification lorsqu'un signal est détecté.
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
# ANALYSE D'UN ACTIF
# ============================================================

def analyze_asset(asset: str):

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

    # ========================================================
    # 4. ALIGNEMENT H1 / M30
    # ========================================================

    if (
        trend_h1 != trend_m30
        or trend_h1 == "neutre"
    ):

        logger.info(
            "%s : pas de tendance claire alignée "
            "(H1=%s, M30=%s)",
            asset,
            trend_h1,
            trend_m30,
        )

        trend_direction = "neutre"

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

    # Mode prudent
    if trend_direction != "neutre":

        for timeframe in config.TIMEFRAMES_ENTRY:

            if timeframe not in timeframes_to_fetch:

                timeframes_to_fetch.append(
                    timeframe
                )

    # Scalping
    if config.SCALPING_ENABLED:

        for timeframe in config.SCALPING_TIMEFRAMES:

            if timeframe not in timeframes_to_fetch:

                timeframes_to_fetch.append(
                    timeframe
                )

    # ========================================================
    # 6. RÉCUPÉRATION UNIQUE DES TIMEFRAMES
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
                "Données manquantes pour %s/%s",
                asset,
                timeframe,
            )

            continue

        candles_by_timeframe[timeframe] = df

    # ========================================================
    # 7. MODE PRUDENT
    # ========================================================

    if trend_direction != "neutre":

        for timeframe in config.TIMEFRAMES_ENTRY:

            df_entry = candles_by_timeframe.get(
                timeframe
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

            df_scalp = candles_by_timeframe.get(
                timeframe
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
                    "crypto continue"
                )

            for asset in config.ASSETS:

                # ------------------------------------------------
                # Forex hors horaires
                # ------------------------------------------------

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
                        "Erreur inattendue lors "
                        "de l'analyse de %s",
                        asset,
                    )

            # ----------------------------------------------------
            # Pause entre les cycles.
            #
            # Le rate limiter de data_fetch.py reste le véritable
            # garde-fou contre les limites Twelve Data.
            # ----------------------------------------------------

            time.sleep(
                config.POLL_INTERVAL_ENTRY
            )

        except Exception:

            logger.exception(
                "Erreur inattendue dans "
                "la boucle principale"
            )

            # Empêche le moteur de redémarrer
            # en boucle instantanément en cas d'erreur.
            time.sleep(30)


# ============================================================
# LANCEMENT DIRECT
# ============================================================

if __name__ == "__main__":

    run_forever()
