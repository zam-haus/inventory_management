"""What the error codes of label_printing.devices (and of the queue) mean, for people."""
from django.utils.translation import gettext_lazy as _

MESSAGES = {
    # Brother P-touch
    "no_media": _("No tape is loaded."),
    "end_of_media": _("The tape is used up."),
    "cutter_jam": _("The cutter is jammed."),
    "weak_batteries": _("The batteries are weak."),
    "high_voltage_adapter": _("The wrong power adapter is connected."),
    "wrong_media": _("The loaded tape does not fit this job."),
    "communication_error": _("The printer reports a communication error."),
    "cover_open": _("The cover is open."),
    "overheating": _("The printer is overheated; wait a moment."),
    "wrong_tape": _("%(loaded_mm)s mm tape is loaded, but %(expected_mm)s mm was chosen."),
    # Zebra
    "paper_out": _("The printer is out of labels."),
    "paused": _("The printer is paused; press its pause button."),
    "head_open": _("The print head is open."),
    "ribbon_out": _("The ribbon is used up."),
    "temperature": _("The print head is too hot or too cold."),
    # Both
    "buffer_full": _("The printer's memory is full."),
    "system_error": _("The printer reports a system error."),
    "printer_error": _("The printer reports an error."),
    "unreachable": _("The printer cannot be reached."),
    "no_response": _("The printer does not answer."),
    "write_failed": _("Sending to the printer failed."),
    "connection_lost": _("The connection to the printer broke off."),
    "no_confirmation": _("The printer took the job but did not confirm it was printed."),
    # Queue
    "expired": _("Nobody picked up the job in time, so it was not printed."),
    "lease_expired": _("The print worker or agent did not report back."),
    "agent_offline": _("The print agent of this printer is offline."),
    "inactive": _("The printer is switched off in the admin."),
}


def describe(code, detail=None):
    """The message for an error code, with its details filled in; "" for no code."""
    if not code:
        return ""
    message = MESSAGES.get(code)
    if message is None:
        return _("Printer error: %(code)s") % {"code": code}
    try:
        return str(message) % (detail or {})
    except (KeyError, TypeError, ValueError):
        return str(message)
