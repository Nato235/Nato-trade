"""
Détermine si le forex doit être analysé en ce moment.
La crypto n'a pas besoin de vérification : elle tourne 24h/24, 7j/7.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from . import config


def is_forex_active() -> bool:
    now = datetime.now(ZoneInfo(config.TRADING_TIMEZONE))
    if now.weekday() not in config.FOREX_ACTIVE_DAYS:
        return False
    return config.FOREX_ACTIVE_HOUR_START <= now.hour < config.FOREX_ACTIVE_HOUR_END
