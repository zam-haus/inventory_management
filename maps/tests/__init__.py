"""The maps tests run only when the app is installed (MAPS_ENABLED); otherwise its models cannot be loaded."""
from pathlib import Path

from django.apps import apps


def load_tests(loader, tests, pattern):
    if not apps.is_installed("maps"):
        return tests
    here = Path(__file__).resolve().parent
    tests.addTests(loader.discover(start_dir=str(here), pattern=pattern or "test*.py",
                                   top_level_dir=str(here.parents[1])))
    return tests
