"""
Envoi des notifications push via ntfy.sh quand un signal est détecté.
"""

import logging
import requests

from . import config
from .signals import Signal

logger = logging.getLogger("nato_trade.notify")


def send_signal_notification(signal: Signal) -> bool:
    emoji = "🟢" if signal.direction == "achat" else "🔴"
    confidence_tag = " ⭐ HAUTE CONFIANCE" if signal.high_confidence else ""
    mode_tag = "[SCALPING]" if signal.mode == "scalping" else "[PRUDENT]"

    title = f"{emoji} {signal.asset} - {signal.direction.upper()} ({signal.timeframe}){confidence_tag}"
    message = (
        f"{mode_tag}\n"
        f"Entrée: {signal.entry_price:.5f}\n"
        f"SL: {signal.stop_loss:.5f}\n"
        f"TP: {signal.take_profit:.5f}\n"
        f"R/R: {signal.rr_ratio:.2f}\n"
        f"Confirmations: {', '.join(signal.confirmations)}"
    )

    try:
        response = requests.post(
            config.NTFY_URL,
            data=message.encode("utf-8"),
            headers={
                "Title": title.encode("utf-8"),
                "Priority": "high" if signal.high_confidence else "default",
                "Tags": "chart_with_upwards_trend" if signal.direction == "achat" else "chart_with_downwards_trend",
            
