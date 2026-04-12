import asyncio
import logging

from app.api.v1.routes.analytics import prewarm_base_data_cache
from app.core.config.settings import settings

logger = logging.getLogger(__name__)


async def run_analytics_prewarm(stop_event: asyncio.Event) -> None:
    interval = max(60, int(settings.analytics_prewarm_interval_seconds))

    # Prime once at startup so the first user request is faster.
    try:
        await prewarm_base_data_cache(force=True)
    except Exception:
        logger.exception("Initial analytics prewarm failed")

    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass

        try:
            await prewarm_base_data_cache(force=True)
        except Exception:
            logger.exception("Periodic analytics prewarm failed")
