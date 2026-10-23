"""
Talking to label printers: sending print data and reading their status.

Plain Python without Django, so the Celery worker (network printers) and the print agent
next to a USB printer (label_printing/agent.py) run the same code: devices.run.run_job.
"""
