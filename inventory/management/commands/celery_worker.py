"""
Utility script for starting Celery worker
"""
import shlex
import subprocess
import imzam.celery
from django.core.management.base import BaseCommand, CommandError

CELERY_APP_NAME = "imzam"


def start_celery(background=False):
    cmd = shlex.split(f'celery -A {CELERY_APP_NAME} worker -l INFO')
    if background:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    else:
        subprocess.call(cmd)


def shutdown_celery():
    cmd = shlex.split(f'celery -A {CELERY_APP_NAME} control shutdown')
    subprocess.call(cmd)


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument(
            'command', help="Command for celery worker (either 'run' or 'stop')", type=str)
        parser.add_argument('--background', action='store_true',
                            default=False, help="Run worker in background")

    def handle(self, *args, **kwargs):
        command = kwargs['command']
        background = kwargs['background']
        if command == 'run':
            print(
                f'Starting celery worker{" in background" if background else ""}')
            start_celery(background)
        elif command == 'stop':
            print('Stopping celery worker')
            if background:
                raise CommandError(
                    f"Invalid option '--background' for 'stop' command")
            shutdown_celery()
        else:
            raise CommandError(
                f"Unknown command: must be either 'run' or 'stop'.")
