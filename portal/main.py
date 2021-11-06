from apscheduler.schedulers.background import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from portal import crawl_portal_notice
from db import truncate_db_all


def job():
    try:
        crawl_portal_notice()
    except SystemExit:
        pass

        
# truncate all board notices (ex. portal, cse, bs,,)
def job1():
    truncate_db_all()


scheduler = BlockingScheduler()
# first at 8:00, last at 18:00
t1 = CronTrigger(day_of_week='mon-fri', hour='8-18', timezone='Asia/Seoul')
t2 = CronTrigger(day_of_week='mon-fri', hour='19', timezone='Asia/Seoul')

scheduler.add_job(job, trigger=t1)
scheduler.add_job(job1, trigger=t2)

print('crawler running,,,,')
scheduler.start()