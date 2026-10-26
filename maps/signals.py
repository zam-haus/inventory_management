"""Follows moves in the inventory (inventory.signals.moved): positions move along or are cleared (positions.py)."""
from inventory.models import Location, UniqueItem
from inventory.signals import moved

from . import positions


def connect():
    moved.connect(positions.location_moved, sender=Location, dispatch_uid="maps.location_moved")
    moved.connect(positions.unique_item_moved, sender=UniqueItem, dispatch_uid="maps.unique_item_moved")
