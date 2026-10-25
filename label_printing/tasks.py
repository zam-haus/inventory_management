from celery import shared_task

from . import services


@shared_task(name="label_printing.tasks.process_job", ignore_result=True)
def process_job(job_id):
    """Print a job on a network printer (queue label_printing; one worker process, one job at a time)."""
    services.process(job_id)


@shared_task(name="label_printing.tasks.dispatch_waiting_jobs", ignore_result=True)
def dispatch_waiting_jobs():
    """Print waiting jobs a printer can print now; schedules itself again while jobs wait."""
    services.dispatch_waiting()


@shared_task(name="label_printing.tasks.check_network_printers", ignore_result=True)
def check_network_printers():
    """Ask the network printers due for it for their status (Celery beat, every PRINT_STATUS_TICK seconds). In the
    print worker's queue: never at the same time as one of its jobs."""
    services.check_network_printers()
