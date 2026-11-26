from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron      import CronTrigger
import pytz, logging

logger    = logging.getLogger(__name__)
TEHRAN_TZ = pytz.timezone("Asia/Tehran")


def setup_scheduler(scan_job, daily_job, sleep_job=None) -> BlockingScheduler:
    """
    scan_job  → every 5 min between 10:00 and 23:55 (Tehran)
    daily_job → every day at 10:00 AM (Tehran)
    sleep_job → every day at 00:00 AM (Tehran)
    """
    scheduler = BlockingScheduler(timezone=TEHRAN_TZ)

    # Scan every 5 minutes from 10:00 AM to 23:55 PM Tehran (Mon-Fri)
    scheduler.add_job(
        scan_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour="10-23", minute="*/5", timezone=TEHRAN_TZ),
        id="gold_scan",
        name="Gold Multi-TF Scanner",
        misfire_grace_time=60,
        max_instances=1,
    )

    # Daily wakeup at 10:00 AM (Mon-Fri)
    scheduler.add_job(
        daily_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour=10, minute=0, timezone=TEHRAN_TZ),
        id="daily_summary",
        name="Daily Wakeup",
        misfire_grace_time=120,
        max_instances=1,
    )

    # Goodnight message at 00:00 midnight (Tue-Sat = end of Mon-Fri sessions)
    if sleep_job is not None:
        scheduler.add_job(
            sleep_job,
            trigger=CronTrigger(day_of_week="tue-sat", hour=0, minute=0, timezone=TEHRAN_TZ),
            id="daily_sleep",
            name="Daily Sleep Notice",
            misfire_grace_time=120,
            max_instances=1,
        )

    logger.info("Scheduler: scan every 5 min (10:00-23:55), wakeup at 10:00, sleep at 00:00")
    return scheduler
