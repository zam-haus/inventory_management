"""Printers, their label media, print agents and the print queue (PrintJob)."""
import hashlib
import io
import secrets
from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from PIL import Image, ImageOps

from . import drivers, messages


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class PrintAgent(models.Model):
    """A program next to USB printers that fetches their jobs (label_printing/agent.py). An admin creates it and
    gives its token to the agent, in its configuration next to the server's address; nothing registers itself."""

    class Meta:
        verbose_name = _("print agent")
        verbose_name_plural = _("print agents")

    name = models.CharField(_("name"), max_length=64, unique=True)
    is_active = models.BooleanField(_("active"), default=True,
                                    help_text=_("Only active agents are let in; deactivate one to lock it out."))
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    hostname = models.CharField(_("host name"), max_length=255, blank=True, editable=False)
    address = models.GenericIPAddressField(_("address"), null=True, blank=True, editable=False)
    last_seen = models.DateTimeField(_("last seen"), null=True, blank=True, editable=False)
    version = models.CharField(_("version"), max_length=32, blank=True, editable=False)

    def __str__(self):
        return self.name

    def new_token(self):
        """Give the agent a new token and return it; only its hash is stored."""
        token = secrets.token_urlsafe(32)
        self.token_hash = token_hash(token)
        return token

    @classmethod
    def for_token(cls, token):
        return cls.objects.filter(token_hash=token_hash(token)).first() if token else None

    @staticmethod
    def online_since():
        return timezone.now() - timedelta(seconds=settings.PRINT_AGENT_OFFLINE_AFTER)

    @property
    def is_online(self):
        return self.last_seen is not None and self.last_seen > self.online_since()


class Winding(models.TextChoices):
    """How labels sit on a Zebra roll: printed side out or in."""
    OUTSIDE = "outside", _("outside")
    INSIDE = "inside", _("inside")


# What Zebra models take, by the model name they report (~HI, e.g. "GK420t"; matched by its start): filled into a
# printer's fields when it is found or its model is set.
ZEBRA_MODELS = {
    "GK420T": {"max_width_mm": 108, "core_mm": Decimal("25.4"), "winding": Winding.OUTSIDE, "thermal_transfer": True},
    "GK420D": {"max_width_mm": 108, "core_mm": Decimal("25.4"), "winding": Winding.OUTSIDE, "thermal_transfer": False},
}


def model_capabilities(language, model):
    """What a printer model takes, for the printer's fields ({} if the model is not known). Brother: the widest tape
    of its print head (ptouch); Zebra: ZEBRA_MODELS."""
    if language == "ptouch":
        if model not in drivers.PTOUCH_MODELS:
            return {}
        return {"max_width_mm": round(max(tape.width_mm for tape in drivers.PTOUCH_MODELS[model].PIN_CONFIGS))}
    name = (model or "").upper()
    return next((dict(values) for key, values in ZEBRA_MODELS.items() if name.startswith(key)), {})


class Printer(models.Model):
    class Meta:
        verbose_name = _("printer")
        verbose_name_plural = _("printers")
        ordering = ("name",)

    class Language(models.TextChoices):
        ZPL = "zpl", _("Zebra (ZPL)")
        PTOUCH = "ptouch", _("Brother P-touch")

    class Transport(models.TextChoices):
        NETWORK = "network", _("Network (TCP, port 9100)")
        AGENT = "agent", _("Print agent (USB)")

    name = models.CharField(_("name"), max_length=64)
    slug = models.SlugField(_("short name"), unique=True,
                            help_text=_("Names the printer, e.g. for a print agent's static printers."))
    uid = models.CharField(_("printer ID"), max_length=128, unique=True, null=True, blank=True, editable=False,
                           help_text=_("Reported by the print agent the printer is connected to (USB IDs and serial number)."))
    info = models.JSONField(_("reported details"), null=True, blank=True, editable=False)
    discovered_at = models.DateTimeField(_("discovered at"), null=True, blank=True, editable=False)
    language = models.CharField(_("printer language"), max_length=16, choices=Language.choices)
    model = models.CharField(
        _("model"), max_length=32, blank=True,
        help_text=_("Brother: E550W, P700, P750W, P710BT, P900, P900W, P950NW or P910BT. Zebra: for information only."),
    )
    dpi = models.PositiveSmallIntegerField(_("resolution (dpi)"), default=203,
                                           help_text=_("Zebra: 203, 300 or 600. Brother: set by the model."))
    transport = models.CharField(_("connection"), max_length=16, choices=Transport.choices, default=Transport.NETWORK)
    host = models.CharField(_("host"), max_length=255, blank=True, help_text=_("Network printers: name or IP address."))
    port = models.PositiveIntegerField(_("port"), default=9100)
    agent = models.ForeignKey(PrintAgent, verbose_name=_("print agent"), null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="printers")
    reports_status = models.BooleanField(
        _("reports its status"), default=True,
        help_text=_("Check paper, tape and errors before printing and wait until the printer reports the "
                    "labels printed. Turn off only for printers that cannot answer."),
    )
    status_interval = models.PositiveIntegerField(
        _("ask for its status every (seconds)"), default=60,
        help_text=_("Network printers, with the print worker (Celery): whether it is online and what is loaded, "
                    "asked unless a job or the print dialog just did; never while it prints. 0: never."),
    )
    # Brother: how labels are cut (drivers.ptouch_job)
    class Cut(models.TextChoices):
        HALF = "half", _("half cut between labels")
        FULL = "full", _("full cut after each label")
        NONE = "none", _("no cut between labels")

    cut = models.CharField(_("cutting"), max_length=8, choices=Cut.choices, default=Cut.HALF,
                           help_text=_("Brother: between the labels of a job."))
    chain_printing = models.BooleanField(
        _("continuous printing"), default=True,
        help_text=_("Brother: the last label stays in the printer and the next job goes on from there, which "
                    "saves tape; cut it off with the printer's cutter button. Off: the printer feeds and cuts "
                    "after every job."))
    # Calibration, for all its labels
    offset_x = models.SmallIntegerField(_("offset x (dots)"), default=0, help_text=_("Zebra: label home (^LH)."))
    offset_y = models.SmallIntegerField(
        _("offset y (dots)"), default=0,
        help_text=_("Zebra: label home (^LH). Brother: moves the print across the tape, positive = down, if the "
                    "top or bottom is cut off (print the calibration label to measure)."))
    # What labels it takes: filled in from its model (model_capabilities); empty: not checked
    max_width_mm = models.PositiveSmallIntegerField(
        _("widest labels (mm)"), null=True, blank=True,
        help_text=_("Zebra: the widest labels; Brother: the widest tape. Filled in from the model."))
    core_mm = models.DecimalField(
        _("roll core (mm)"), max_digits=4, decimal_places=1, null=True, blank=True,
        help_text=_("Zebra: the core of the label rolls it holds, e.g. 25.4 (1 inch). Filled in from the model."))
    winding = models.CharField(
        _("labels wound"), max_length=8, choices=Winding.choices, blank=True,
        help_text=_("Zebra: the labels on the roll it takes, outside or inside; empty: either. Filled in from the "
                    "model."))
    thermal_transfer = models.BooleanField(
        _("prints thermal transfer"), default=True,
        help_text=_("Zebra: has a ribbon; off for direct thermal models (e.g. GK420d). Filled in from the model."))
    # Zebra: which labels are loaded; a Zebra measures only the labels' length (checked), not their width
    loaded_medium = models.ForeignKey(
        "LabelStock", verbose_name=_("loaded labels"), null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
        help_text=_("Zebra: the labels in the printer now; set it when changing labels. Only these are printed, "
                    "after comparing their height with the label length the printer measured (it cannot tell "
                    "their width)."))
    loaded_ribbon = models.ForeignKey(
        "Ribbon", verbose_name=_("loaded ribbon"), null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text=_("Zebra: the ribbon in the printer now; set it when changing ribbons. Its material (wax, "
                    "wax/resin, resin) is compared with what the loaded labels need, and the print agent's display "
                    "warns if it does not suit them."))
    is_active = models.BooleanField(_("active"), default=True)
    is_default = models.BooleanField(_("default printer"), default=False,
                                     help_text=_("Used by the print actions in the admin."))
    last_status = models.JSONField(_("last status"), null=True, blank=True, editable=False)
    last_status_at = models.DateTimeField(_("last status at"), null=True, blank=True, editable=False)
    # held on its print agent (on the display, or by pausing a job): no job starts there until it goes on, whoever
    # held it and whatever became of the jobs; the agent reports it with each poll
    held_at = models.DateTimeField(_("held since"), null=True, blank=True, editable=False)
    resume_requested = models.BooleanField(_("asked to go on"), default=False, editable=False)

    def __str__(self):
        return self.name

    def clean(self):
        errors = {}
        before = Printer.objects.filter(pk=self.pk).values("language", "model").first() if self.pk else None
        if before and (before["language"], before["model"]) != (self.language, self.model):
            errors["model"] = _("The model of a printer cannot be changed: delete the printer and add it anew.")
        if self.language == self.Language.PTOUCH:
            if self.model not in drivers.PTOUCH_MODELS:
                errors["model"] = _("Choose one of %(models)s.") % {"models": ", ".join(drivers.PTOUCH_MODELS)}
            else:
                self.dpi = drivers.ptouch_dpi(self.model)
        if self.transport == self.Transport.NETWORK and not self.host:
            errors["host"] = _("Network printers need a host.")
        if self.transport == self.Transport.AGENT and not self.agent_id:
            errors["agent"] = _("Choose the print agent the printer is connected to.")
        if self.loaded_medium_id and (reason := self.takes(self.loaded_medium)):
            errors["loaded_medium"] = reason
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self._state.adding:  # what its model takes, where not given otherwise (the model is fixed: clean)
            for field, value in model_capabilities(self.language, self.model).items():
                if getattr(self, field) == Printer._meta.get_field(field).get_default():
                    setattr(self, field, value)
        with transaction.atomic():
            if self.is_default:
                Printer.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)
            super().save(*args, **kwargs)

    def takes(self, stock):
        """Why the printer cannot take these labels, in words, or "": by kind of printer; Brother: the tape width
        (its print head, the widest tape); Zebra: label width, roll core, winding, printing method. What is not known
        is not checked."""
        if stock.language != self.language:
            return _("These labels are for another kind of printer.")
        if self.language == self.Language.PTOUCH:
            known = self.model in drivers.PTOUCH_MODELS
            if stock.tape_mm and ((known and drivers.ptouch_tape(stock.tape_mm)
                                   not in drivers.PTOUCH_MODELS[self.model].PIN_CONFIGS)
                                  or (self.max_width_mm and stock.tape_mm > self.max_width_mm)):
                return _("The printer does not take %(width)s tape.") % {"width": stock.get_tape_mm_display()}
            return ""
        if self.max_width_mm and stock.width_mm and stock.width_mm > self.max_width_mm:
            return _("The labels are wider than the printer takes (%(max)s mm).") % {"max": self.max_width_mm}
        if self.core_mm and stock.core_mm and stock.core_mm != self.core_mm:
            return _("The roll core (%(core)s mm) does not fit the printer (%(printer)s mm).") % {
                "core": stock.core_mm, "printer": self.core_mm}
        if self.winding and stock.winding and stock.winding != self.winding:
            return _("The labels are wound %(labels)s, the printer takes them %(printer)s.") % {
                "labels": stock.get_winding_display(), "printer": self.get_winding_display()}
        if stock.method == LabelStock.Method.TRANSFER and not self.thermal_transfer:
            return _("These labels need a ribbon, the printer prints direct thermal only.")
        return ""

    def media(self, in_stock=True):
        """The labels the printer takes, each as a Medium: of the label materials on hand (in_stock=False: of all)."""
        stocks = LabelStock.objects.filter(language=self.language)
        if in_stock:
            stocks = stocks.filter(in_stock=True)
        return [Medium(self, stock) for stock in stocks if not self.takes(stock)]

    def unavailable_code(self):
        """Why jobs cannot be printed now ("inactive", "agent_offline"), or ""."""
        if not self.is_active:
            return "inactive"
        # Asked of the database: the agent's last request may be newer than a loaded copy of it.
        if self.transport == self.Transport.AGENT and not PrintAgent.objects.filter(
                pk=self.agent_id, is_active=True, last_seen__gt=PrintAgent.online_since()).exists():
            return "agent_offline"
        return ""

    def unavailable_reason(self):
        return messages.describe(self.unavailable_code())

    def remember_status(self, status):
        if status is None:
            return
        if status.get("label_length_dots") and self.dpi:
            status = {**status, "label_length_mm": round(status["label_length_dots"] * 25.4 / self.dpi)}
        self.last_status, self.last_status_at = status, timezone.now()
        Printer.objects.filter(pk=self.pk).update(last_status=status, last_status_at=self.last_status_at)

    def ribbon_problem(self):
        """Zebra: why the loaded ribbon does not suit the loaded labels, or "" (see ribbon_problem)."""
        if self.language != self.Language.ZPL:
            return ""
        return ribbon_problem(self.loaded_medium, self.loaded_ribbon)

    @property
    def status_text(self):
        """The last known status in words."""
        status = self.last_status
        if not status:
            return ""
        if status.get("errors"):
            return messages.describe(status["errors"][0])
        return " ".join(str(part) for part in (_("Ready."), loaded_text(status)) if part)


def loaded_text(status):
    """What a printer reports to be loaded: "12 mm tape, black on white" or "labels 32 mm long, thermal transfer"."""
    if status.get("media_width_mm"):
        text = _("%(width)s mm tape") % {"width": status["media_width_mm"]}
        if status.get("text_color") and status.get("tape_color"):
            text += ", " + _("%(print)s on %(background)s") % {"print": status["text_color"],
                                                                 "background": status["tape_color"]}
        return _("Loaded: %(media)s.") % {"media": text}
    parts = []
    if status.get("label_length_mm"):
        parts.append(_("labels %(length)s mm long") % {"length": status["label_length_mm"]})
    if "thermal_transfer" in status:
        parts.append(LabelStock.Method.TRANSFER.label if status["thermal_transfer"] else LabelStock.Method.DIRECT.label)
    return _("Loaded: %(media)s.") % {"media": ", ".join(str(part) for part in parts)} if parts else ""


TAPE_CHOICES = [(width, f"{width if width != 4 else 3.5} mm") for width in drivers.PTOUCH_TAPES]


class Quality(models.TextChoices):
    """Print quality: Brother draft printing or high resolution; Zebra print speed (drivers.ZPL_SPEEDS)."""
    DRAFT = "draft", _("draft (fast)")
    STANDARD = "standard", _("standard")
    HIGH = "high", _("high quality (slower)")


class LabelStock(models.Model):
    """Label material (catalog): Brother tapes with their colours, Zebra labels with their size, roll, printing
    method and ribbon. A printer prints on the material on hand that it takes (Printer.takes, Printer.media)."""

    class Meta:
        verbose_name = _("label material")
        verbose_name_plural = _("label material")
        ordering = ("language", "tape_mm", "width_mm", "height_mm", "code", "name")
        constraints = [models.UniqueConstraint(fields=["code"], condition=~models.Q(code=""),
                                               name="label_stock_unique_code")]

    class Method(models.TextChoices):
        DIRECT = "direct", _("direct thermal")
        TRANSFER = "transfer", _("thermal transfer")

    class Ribbon(models.TextChoices):
        WAX = "wax", _("wax ribbon")
        WAX_RESIN = "wax_resin", _("wax/resin ribbon")
        RESIN = "resin", _("resin ribbon")

    language = models.CharField(_("printer language"), max_length=16, choices=Printer.Language.choices)
    code = models.CharField(_("article number"), max_length=64, blank=True)
    name = models.CharField(_("name"), max_length=128)
    description = models.TextField(_("description"), blank=True)
    # Brother
    tape_mm = models.PositiveSmallIntegerField(_("tape width"), choices=TAPE_CHOICES, null=True, blank=True)
    background_color = models.CharField(_("background colour"), max_length=64, blank=True)
    print_color = models.CharField(_("print colour"), max_length=64, blank=True)
    length_m = models.DecimalField(_("length (m)"), max_digits=6, decimal_places=2, null=True, blank=True)
    # Zebra
    width_mm = models.PositiveSmallIntegerField(_("width (mm)"), null=True, blank=True)
    height_mm = models.PositiveSmallIntegerField(
        _("height (mm)"), null=True, blank=True,
        help_text=_("Zebra: the label height. Brother: a fixed label length; empty for as long as the content."))
    method = models.CharField(_("printing method"), max_length=16, choices=Method.choices, blank=True,
                              help_text=_("Zebra: direct thermal labels need no ribbon. Empty: not known."))
    ribbon = models.CharField(_("ribbon"), max_length=16, choices=Ribbon.choices, blank=True,
                              help_text=_("Thermal transfer: the ribbon the material needs."))
    material = models.CharField(_("material"), max_length=64, blank=True,
                                help_text=_("e.g. paper, polypropylene, polyester"))
    url = models.URLField(_("product page"), blank=True)
    in_stock = models.BooleanField(_("on hand"), default=False,
                                   help_text=_("Only material on hand is offered for printing and waited for."))
    quality = models.CharField(
        _("print quality"), max_length=16, choices=Quality.choices, default=Quality.STANDARD,
        help_text=_("Unless the label template sets it. Brother: draft printing or high resolution; Zebra: print "
                    "speed."))
    # Zebra
    core_mm = models.DecimalField(_("roll core (mm)"), max_digits=4, decimal_places=1, null=True, blank=True,
                                  help_text=_("Zebra: inner diameter of the core, e.g. 25.4 (1 inch)."))
    winding = models.CharField(_("labels wound"), max_length=8, choices=Winding.choices, blank=True,
                               help_text=_("Zebra: printed side outside or inside on the roll."))
    zpl_darkness = models.SmallIntegerField(_("darkness"), null=True, blank=True,
                                            help_text=_("Zebra: -30 to 30 (^MD); empty for the printer's setting."))

    def __str__(self):
        if self.language == Printer.Language.PTOUCH:
            colours = _("%(print)s on %(background)s") % {"print": self.print_color, "background": self.background_color} \
                if self.print_color and self.background_color else ""
            return " ".join(part for part in (self.code, self.get_tape_mm_display() if self.tape_mm else "", colours,
                                              f"({self.description_short})" if self.description_short else "") if part)
        return " ".join(part for part in (self.code, self.name) if part)

    @property
    def description_short(self):
        """Brother: the tape kind ("Extra-stark klebend, laminiert"), kept in the first line of the description."""
        return self.description.splitlines()[0] if self.description else ""

    @property
    def method_text(self):
        """"thermal transfer, resin ribbon" or "direct thermal"."""
        return ", ".join(str(part) for part in (self.get_method_display(), self.get_ribbon_display()) if part)

    def clean(self):
        errors = {}
        if self.language == Printer.Language.PTOUCH:
            if not self.tape_mm:
                errors["tape_mm"] = _("Choose the tape width.")
        else:
            if not self.width_mm:
                errors["width_mm"] = _("Zebra labels need a width.")
            if not self.height_mm:
                errors["height_mm"] = _("Zebra labels need a height.")
            if self.method == self.Method.TRANSFER and not self.ribbon:
                errors["ribbon"] = _("Thermal transfer labels need a ribbon: choose which.")
            if self.method != self.Method.TRANSFER and self.ribbon:
                errors["ribbon"] = _("Only thermal transfer labels take a ribbon.")
            if self.zpl_darkness is not None and not -30 <= self.zpl_darkness <= 30:
                errors["zpl_darkness"] = _("Between -30 and 30.")
        if errors:
            raise ValidationError(errors)


class Ribbon(models.Model):
    """A kind of thermal transfer ribbon (catalog): material, width and colour; changed in a Zebra like its labels
    (Printer.loaded_ribbon)."""

    class Meta:
        verbose_name = _("ribbon")
        verbose_name_plural = _("ribbons")
        ordering = ("width_mm", "color", "material")
        constraints = [models.UniqueConstraint(fields=["material", "width_mm", "color"], name="ribbon_unique")]

    material = models.CharField(_("material"), max_length=16, choices=LabelStock.Ribbon.choices)
    width_mm = models.PositiveSmallIntegerField(_("width (mm)"))
    color = models.CharField(_("colour"), max_length=64, default="schwarz",
                             help_text=_("What a Zebra prints in with this ribbon (label templates and previews)."))

    def __str__(self):
        return f"{self.get_material_display()} {self.width_mm} mm, {self.color}"


# The ribbons that print well on labels made for a kind of ribbon (LabelStock.ribbon): a stronger one mostly
# does; a weaker one smears or rubs off, and resin does not hold on paper labels made for wax.
RIBBON_FITS = {
    LabelStock.Ribbon.WAX: {LabelStock.Ribbon.WAX, LabelStock.Ribbon.WAX_RESIN},
    LabelStock.Ribbon.WAX_RESIN: {LabelStock.Ribbon.WAX_RESIN, LabelStock.Ribbon.RESIN},
    LabelStock.Ribbon.RESIN: {LabelStock.Ribbon.RESIN},
}


def ribbon_problem(stock, ribbon):
    """Why the ribbon does not suit the labels (label material), in words, or "": compared by material only, and only
    when both are known (labels for thermal transfer with their ribbon, a ribbon set as loaded)."""
    if stock is None or ribbon is None or stock.method != LabelStock.Method.TRANSFER or not stock.ribbon:
        return ""
    if ribbon.material in RIBBON_FITS[stock.ribbon]:
        return ""
    return _("The ribbon does not suit the labels: %(labels)s need a %(needed)s, the loaded one is a %(ribbon)s.") % {
        "labels": stock.name, "needed": stock.get_ribbon_display(), "ribbon": ribbon}


class Medium:
    """Labels of a label material on a printer: what is drawn and printed on. Not stored: the material's size,
    colours, darkness and quality with the printer's calibration (offsets)."""

    def __init__(self, printer, stock):
        self.printer, self.stock = printer, stock

    def __eq__(self, other):
        return isinstance(other, Medium) and (self.printer.pk, self.stock.pk) == (other.printer.pk, other.stock.pk)

    def __hash__(self):
        return hash((self.printer.pk, self.stock.pk))

    def __repr__(self):
        return f"<Medium {self.printer} – {self.stock.name}>"

    def __str__(self):
        return self.name

    pk = property(lambda self: self.stock.pk)
    stock_id = property(lambda self: self.stock.pk)
    printer_id = property(lambda self: self.printer.pk)
    name = property(lambda self: self.stock.name or str(self.stock))
    ptouch_tape = property(lambda self: self.stock.tape_mm if self.is_tape else None)
    width_mm = property(lambda self: None if self.is_tape else self.stock.width_mm)
    height_mm = property(lambda self: self.stock.height_mm)  # Brother: a fixed label length, or None
    offset_x = property(lambda self: self.printer.offset_x)
    offset_y = property(lambda self: self.printer.offset_y)
    zpl_darkness = property(lambda self: self.stock.zpl_darkness)
    quality = property(lambda self: self.stock.quality)

    @property
    def is_tape(self):
        return self.printer.language == Printer.Language.PTOUCH

    def colours(self):
        """(print colour, background colour) of the labels, "" where not known: as the label material says, but a
        Zebra prints in the colour of its loaded ribbon (unless the labels are direct thermal)."""
        stock, printer = self.stock, self.printer
        print_color, background = stock.print_color, stock.background_color
        if (printer.language == Printer.Language.ZPL and printer.loaded_ribbon_id
                and stock.method != LabelStock.Method.DIRECT):
            print_color = printer.loaded_ribbon.color
        return print_color, background


class PrintJob(models.Model):
    """One print request: the printer-ready data and what became of it. A job asked for while no printer can
    print it waits (WAITING) without printer and data, until one can (services.dispatch_waiting) or it expires."""

    class Meta:
        verbose_name = _("print job")
        verbose_name_plural = _("print jobs")
        ordering = ("-created_at",)
        permissions = [("print_label", _("Can print labels"))]
        indexes = [models.Index(fields=["printer", "status", "created_at"])]

    class Status(models.TextChoices):
        WAITING = "waiting", _("waiting for a printer")
        PENDING = "pending", _("waiting")
        PROCESSING = "processing", _("printing")
        DONE = "done", _("printed")
        SENT = "sent", _("sent, not confirmed")
        FAILED = "failed", _("failed")
        EXPIRED = "expired", _("expired")

    FINISHED = (Status.DONE, Status.SENT, Status.FAILED, Status.EXPIRED)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("user"), null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="+")
    printer = models.ForeignKey(Printer, verbose_name=_("printer"), null=True, blank=True, on_delete=models.PROTECT,
                                related_name="jobs")
    medium = models.ForeignKey(LabelStock, verbose_name=_("label material"), null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="+")
    layout_key = models.CharField(_("layout"), max_length=64)
    subject_type = models.CharField(_("subject type"), max_length=32)
    subject_id = models.PositiveBigIntegerField(_("subject ID"), null=True, blank=True)
    subject_label = models.CharField(_("subject"), max_length=255, blank=True)
    label_code = models.CharField(_("code in the QR code"), max_length=64, blank=True)
    # What is on each printed label (code, name, price …), to find labels that are out of date.
    snapshot = models.JSONField(_("printed content"), default=list, blank=True)
    copies = models.PositiveSmallIntegerField(_("copies"), default=1)
    pages = models.PositiveSmallIntegerField(_("labels"), default=1)
    quality = models.CharField(_("print quality"), max_length=16, choices=Quality.choices, default=Quality.STANDARD)
    payload = models.BinaryField(null=True, blank=True, editable=False)
    status = models.CharField(_("status"), max_length=16, choices=Status.choices, default=Status.PENDING)
    code = models.CharField(_("result"), max_length=64, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    printer_status = models.JSONField(_("printer status"), null=True, blank=True)
    agent = models.ForeignKey(PrintAgent, verbose_name=_("print agent"), null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    claimed_by = models.CharField(_("processed by"), max_length=64, blank=True)

    class Command(models.TextChoices):
        PAUSE = "pause", _("pause")
        RESUME = "resume", _("go on")
        ABORT = "abort", _("abort")

    # For the print agent printing it, from the admin: sent with its polls until it did so.
    command = models.CharField(_("command for the print agent"), max_length=8, choices=Command.choices, blank=True)
    # Since when the agent holds the job (paused on its display or by a command); None while it prints.
    paused_at = models.DateTimeField(_("paused since"), null=True, blank=True)
    request_id = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    # The jobs of one print from the dialog's overview (one job per label), followed together
    batch = models.UUIDField(_("batch"), null=True, blank=True, editable=False, db_index=True)
    # A waiting job: the label outcome asked for (outcomes.py), its subjects and options, until when it waits.
    outcome = models.CharField(_("label"), max_length=96, blank=True)
    request = models.JSONField(default=dict, blank=True, editable=False)
    expires_at = models.DateTimeField(_("waits until"), null=True, blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    # When its data was ready for the printer: picked up within PRINT_JOB_MAX_AGE from then.
    ready_at = models.DateTimeField(default=timezone.now, editable=False)
    claimed_at = models.DateTimeField(_("picked up at"), null=True, blank=True)
    finished_at = models.DateTimeField(_("finished at"), null=True, blank=True)

    def __str__(self):
        return f"#{self.pk} {self.subject_label} → {self.printer or self.get_status_display()}"

    @property
    def is_finished(self):
        return self.status in self.FINISHED

    @property
    def message(self):
        """The outcome in words: the error, or the plain status (paused on its print agent)."""
        if self.status == self.Status.PROCESSING and self.paused_at:
            return str(messages.describe("paused_by_agent"))
        return messages.describe(self.code, self.detail) or self.get_status_display()


class LastLabel(models.Model):
    """The label template chosen for a subject in the print dialog ("preselect from now on"; selection.py
    preselects it): e.g. the arrow up or down for a compartment, which no rule could tell. By its layout key ("design:12", as PrintJob.layout_key),
    so label printing has no relation to the inventory's models."""

    class Meta:
        verbose_name = _("last label")
        verbose_name_plural = _("last labels")
        constraints = [models.UniqueConstraint(fields=["subject_type", "subject_pk"], name="last_label_per_subject")]

    subject_type = models.CharField(_("subject type"), max_length=32)
    subject_pk = models.CharField(_("subject"), max_length=64)
    layout_key = models.CharField(_("layout"), max_length=64)
    printed_at = models.DateTimeField(_("printed at"), default=timezone.now)

    def __str__(self):
        return f"{self.subject_type} {self.subject_pk}: {self.layout_key}"


class LabelImage(models.Model):
    """An image for label designs (a logo, a safety sign, a tool icon), stored once in its full size and cropped
    here. Designs scale it for each printer and turn it black and white (label_printing.design)."""

    class Meta:
        verbose_name = _("label image")
        verbose_name_plural = _("label images")
        ordering = ("name",)

    name = models.CharField(_("name"), max_length=64, unique=True,
                            help_text=_("Designs use it by this name: image \"ZAM Logo\"."))
    image = models.ImageField(_("original"), upload_to="label_images/",
                              help_text=_("PNG, GIF, JPEG or WebP, best large: designs scale it down."))
    crop_left = models.PositiveIntegerField(_("cut off left"), default=0)
    crop_top = models.PositiveIntegerField(_("cut off top"), default=0)
    crop_right = models.PositiveIntegerField(_("cut off right"), default=0)
    crop_bottom = models.PositiveIntegerField(_("cut off bottom"), default=0)

    def __str__(self):
        return self.name

    def picture(self):
        """The original as a Pillow image, EXIF rotation applied. An upload not yet saved stays open for saving."""
        if self.image._committed:
            with self.image.open("rb") as file:
                data = file.read()
        else:
            self.image.seek(0)
            data = self.image.read()
            self.image.seek(0)
        return ImageOps.exif_transpose(Image.open(io.BytesIO(data)))

    def size(self):
        """The original's size in pixels (as shown, EXIF rotation applied)."""
        return self.picture().size

    def cropped(self):
        """The cropped original in grey, transparency as white."""
        image = self.picture().convert("RGBA")
        image = Image.alpha_composite(Image.new("RGBA", image.size, "white"), image).convert("L")
        return image.crop((self.crop_left, self.crop_top, image.width - self.crop_right, image.height - self.crop_bottom))

    def clean(self):
        if not self.image:
            return
        try:
            width, height = self.size()
        except (OSError, ValueError):
            raise ValidationError({"image": _("The file is not an image that can be read.")}) from None
        if self.crop_left + self.crop_right >= width or self.crop_top + self.crop_bottom >= height:
            raise ValidationError(_("Cut off less than the image: it is %(width)s × %(height)s pixels.") % {
                "width": width, "height": height})
