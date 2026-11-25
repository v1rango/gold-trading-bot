from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron      import CronTrigger
import pytz, logging

logger    = logging.getLogger(__name__)
TEHRAN_TZ = pytz.timezone("Asia/Tehran")


def setup_scheduler(scan_job, daily_job, sleep_job=None) -> BlockingScheduler:
    """
    scan_job  → every 10 min between 12:00 and 23:50 (Tehran)
    daily_job → every day at 12:00 (Tehran)
    sleep_job → every day at 00:00 (Tehran)
    """
    scheduler = BlockingScheduler(timezone=TEHRAN_TZ)

    # Scan every 10 minutes from 12:00 to 23:50
    scheduler.add_job(
        scan_job,
        trigger=CronTrigger(hour="12-23", minute="*/10", timezone=TEHRAN_TZ),
        id="gold_scan",
        name="Gold Scanner",
        misfire_grace_time=60,
        max_instances=1,
    )

    # Daily wakeup / summary at 12:00
    scheduler.add_job(
        daily_job,
        trigger=CronTrigger(hour=12, minute=0, timezone=TEHRAN_TZ),
        id="daily_summary",
        name="Daily Wakeup & Summary",
        misfire_grace_time=120,
        max_instances=1,
    )

    # Goodnight message at 00:00 midnight
    if sleep_job is not None:
        scheduler.add_job(
            sleep_job,
            trigger=CronTrigger(hour=0, minute=0, timezone=TEHRAN_TZ),
            id="daily_sleep",
            name="Daily Sleep Notice",
            misfire_grace_time=120,
            max_instances=1,
        )

    logger.info("Scheduler: scan every 10 min (12:00-23:50), wakeup at 12:00, sleep at 00:00")
    return scheduler
