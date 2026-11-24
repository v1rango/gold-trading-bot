from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron      import CronTrigger
import pytz, logging

logger    = logging.getLogger(__name__)
TEHRAN_TZ = pytz.timezone("Asia/Tehran")


def setup_scheduler(scan_job, daily_job) -> BlockingScheduler:
    """
    scan_job  → every 15 min between 12:00 and 23:45 (Tehran)
    daily_job → every day at 12:00 (Tehran)
    """
    scheduler = BlockingScheduler(timezone=TEHRAN_TZ)

    # Scan: :00 :15 :30 :45 of each hour from 12 to 23
    scheduler.add_job(
        scan_job,
        trigger=CronTrigger(hour="12-23", minute="0,15,30,45", timezone=TEHRAN_TZ),
        id="gold_scan",
        name="Gold Scanner",
        misfire_grace_time=60,
        max_instances=1,
    )

    # Daily summary at 12:00
    scheduler.add_job(
        daily_job,
        trigger=CronTrigger(hour=12, minute=0, timezone=TEHRAN_TZ),
        id="daily_summary",
        name="Daily Summary",
        misfire_grace_time=120,
        max_instances=1,
    )

    logger.info("Scheduler: scan every 15 min (12:00-23:45), daily summary at 12:00")
    return scheduler
