"""
Point d'entrée du serveur Nato Trade.
Tourne en continu : vérifie la tendance H1/M30 pour chaque actif,
et si le feu est vert, cherche des signaux d'entrée sur M15/M5/M1.
Envoie une notification ntfy.sh dès qu'un signal valide est détecté.
Le forex n'est analysé que Lun-Ven 8h-21h (Tchad), la crypto tourne 24/7.
"""

import logging
import time

from . import config, data_fetch, indicators, signals, notify, database, schedule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("nato_trade.main")


def analyze_asset(asset: str):
    df_h1 = data_fetch.fetch_candles(asset, "1h")
    df_m30 = data_fetch.fetch_candles(asset, "30min")

    if df_h1.empty or df_m30.empty:
        logger.warning("Données manquantes pour %s, on passe", asset)
        return

    df_h1 = indicators.add_trend_indicators(df_h1)
    df_m30 = indicators.add_trend_indicators(df_m30)

    trend_h1 = indicators.get_trend_direction(df_h1)
    trend_m30 = indicators.get_trend_direction(df_m30)

    database.log_trend_analysis(asset, f"H1:{trend_h1}/M30:{trend_m30}")

    if trend_h1 != trend_m30 or trend_h1 == "neutre":
        logger.info("%s : pas de tendance claire alignée (H1=%s, M30=%s)", asset, trend_h1, trend_m30)
        trend_direction = "neutre"
    else:
        trend_direction = trend_h1
        logger.info("%s : tendance de fond = %s", asset, trend_direction)

    if trend_direction != "neutre":
        for timeframe in config.TIMEFRAMES_ENTRY:
            df_entry = data_fetch.fetch_candles(asset, timeframe)
            if df_entry.empty:
                continue

            signal = signals.evaluate_entry(asset, timeframe, df_entry, trend_direction, mode="prudent")
            if signal:
                logger.info("SIGNAL PRUDENT détecté : %s %s %s", asset, timeframe, signal.direction)
                database.save_signal(signal)
                notify.send_signal_notification(signal)

    if config.SCALPING_ENABLED:
        for timeframe in config.SCALPING_TIMEFRAMES:
            df_scalp = data_fetch.fetch_candles(asset, timeframe)
            if df_scalp.empty:
                continue
            signal = signals.evaluate_entry(asset, timeframe, df_scalp, trend_direction, mode="scalping")
            if signal:
                logger.info("SIGNAL SCALPING détecté : %s %s %s", asset, timeframe, signal.direction)
                database.save_signal(signal)
                notify.send_signal_notification(signal)


def run_forever():
    database.init_db()
    logger.info("Nato Trade démarré. Actifs suivis: %s", ", ".join(config.ASSETS))

    while True:
        forex_active = schedule.is_forex_active()
        if not forex_active:
            logger.info("Hors horaires forex (Lun-Ven 8h-21h) : forex mis en pause, crypto continue")

        for asset in config.ASSETS:
            if asset in config.FOREX_ASSETS and not forex_active:
                continue
            try:
                analyze_asset(asset)
            except Exception:
                logger.exception("Erreur inattendue lors de l'analyse de %s", asset)

        time.sleep(config.POLL_INTERVAL_ENTRY)


if __name__ == "__main__":
    run_forever()
