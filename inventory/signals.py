"""Signals for optional apps (e.g. maps) that follow what happens in the inventory without it knowing them."""
from django.dispatch import Signal

# A location got another parent, or a unique item another location (also when disposed: then the new one is
# None). Sent with sender=the model class, inside the saving transaction, with:
#   instance:    the saved location or unique item
#   old_parent:  pk of the location it was in before (None if it was nowhere)
#   context:     what the view attached as instance.move_context before saving (e.g. request.POST), else {}
moved = Signal()


def send_moved(instance, old_parent):
    """Sends `moved` once for this save; the move context is used up with it."""
    context = instance.__dict__.pop("move_context", None) or {}
    moved.send(sender=type(instance), instance=instance, old_parent=old_parent, context=context)
