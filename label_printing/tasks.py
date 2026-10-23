from celery import shared_task

from . import services


@shared_task(name="label_printing.tasks.process_job", ignore_result=True)
def process_job(job_id):
    """Print a job on a network printer (queue label_printing; one worker process, one job at a time)."""
    services.process(job_id)
