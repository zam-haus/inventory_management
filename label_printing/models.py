"""Printers, their label media, print agents and the print queue (PrintJob)."""
import hashlib
import io
import secrets
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
    """A program next to USB printers that fetches their jobs (label_printing/agent.py). Agents register
    themselves (api.register) and get jobs once an admin activates them."""

    class Meta:
        verbose_name = _("print agent")
        verbose_name_plural = _("print agents")

    name = models.CharField(_("name"), max_length=64, unique=True)
    uid = models.CharField(_("agent ID"), max_length=128, unique=True, null=True, blank=True, editable=False,
                           help_text=_("Reported by an agent that registered itself."))
    is_active = models.BooleanField(_("active"), default=True,
                                    help_text=_("Only active agents get jobs; agents that register themselves start inactive."))
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    hostname = models.CharField(_("host name"), max_length=255, blank=True, editable=False)
    address = models.GenericIPAddressField(_("address"), null=True, blank=True, editable=False)
    registered_at = models.DateTimeField(_("registered at"), null=True, blank=True, editable=False)
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
        help_text=_("Brother: E550W, P750W, P900, P900W or P950NW. Zebra: for information only."),
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
    # Zebra: which of its media is loaded; a Zebra measures only the labels' length (checked), not their width
    loaded_medium = models.ForeignKey(
        "LabelMedium", verbose_name=_("loaded labels"), null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
        help_text=_("Zebra: the labels in the printer now; set it when changing labels. Only these are printed, "
                    "after comparing their height with the label length the printer measured (it cannot tell "
                    "their width)."))
    is_active = models.BooleanField(_("active"), default=True)
    is_default = models.BooleanField(_("default printer"), default=False,
                                     help_text=_("Used by the print actions in the admin."))
    last_status = models.JSONField(_("last status"), null=True, blank=True, editable=False)
    last_status_at = models.DateTimeField(_("last status at"), null=True, blank=True, editable=False)

    def __str__(self):
        return self.name

    def clean(self):
        errors = {}
        if self.language == self.Language.PTOUCH:
            if self.model not in drivers.PTOUCH_MODELS:
                errors["model"] = _("Choose one of %(models)s.") % {"models": ", ".join(drivers.PTOUCH_MODELS)}
            else:
                self.dpi = drivers.ptouch_dpi(self.model)
        if self.transport == self.Transport.NETWORK and not self.host:
            errors["host"] = _("Network printers need a host.")
        if self.transport == self.Transport.AGENT and not self.agent_id:
            errors["agent"] = _("Choose the print agent the printer is connected to.")
        if self.loaded_medium_id and (self.pk is None or self.loaded_medium.printer_id != self.pk):
            errors["loaded_medium"] = _("Choose labels of this printer.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_default:
                Printer.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)
            super().save(*args, **kwargs)

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
    """A kind of labels or tape (catalog): Brother tapes with their colours, Zebra labels with their size,
    printing method and ribbon. Printers' media are set up from them."""

    class Meta:
        verbose_name = _("label stock")
        verbose_name_plural = _("label stock")
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
    height_mm = models.PositiveSmallIntegerField(_("height (mm)"), null=True, blank=True)
    method = models.CharField(_("printing method"), max_length=16, choices=Method.choices, blank=True,
                              help_text=_("Zebra: direct thermal labels need no ribbon. Empty: not known."))
    ribbon = models.CharField(_("ribbon"), max_length=16, choices=Ribbon.choices, blank=True,
                              help_text=_("Thermal transfer: the ribbon the material needs."))
    material = models.CharField(_("material"), max_length=64, blank=True,
                                help_text=_("e.g. paper, polypropylene, polyester"))
    label_templates = models.ManyToManyField(
        "inventory.LocationLabelTemplate", verbose_name=_("label templates"), blank=True, related_name="stock",
        help_text=_("Only these of their kind for these labels; none: every template of the labels' size."),
    )
    url = models.URLField(_("product page"), blank=True)

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
        if errors:
            raise ValidationError(errors)


class LabelMedium(models.Model):
    """Labels or tape loaded in a printer."""

    class Meta:
        verbose_name = _("label medium")
        verbose_name_plural = _("label media")
        ordering = ("printer", "name")

    TAPE_CHOICES = TAPE_CHOICES

    printer = models.ForeignKey(Printer, verbose_name=_("printer"), on_delete=models.CASCADE, related_name="media")
    stock = models.ForeignKey(LabelStock, verbose_name=_("label stock"), null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="media",
                              help_text=_("Fills in name, size and tape; colours and material come from it."))
    name = models.CharField(_("name"), max_length=128, blank=True)
    width_mm = models.PositiveSmallIntegerField(_("width (mm)"), null=True, blank=True,
                                                help_text=_("Zebra: the label width."))
    height_mm = models.PositiveSmallIntegerField(
        _("height / length (mm)"), null=True, blank=True,
        help_text=_("Zebra: the label height. Brother: a fixed label length; empty for as long as the content."),
    )
    ptouch_tape = models.PositiveSmallIntegerField(_("tape width"), choices=TAPE_CHOICES, null=True, blank=True,
                                                   help_text=_("Brother only."))
    offset_x = models.SmallIntegerField(_("offset x (dots)"), default=0, help_text=_("Zebra: label home (^LH)."))
    offset_y = models.SmallIntegerField(
        _("offset y (dots)"), default=0,
        help_text=_("Zebra: label home (^LH). Brother: moves the print across the tape, positive = down, if the "
                    "top or bottom is cut off (print the calibration label to measure)."),
    )
    zpl_darkness = models.SmallIntegerField(_("darkness"), null=True, blank=True,
                                            help_text=_("Zebra: -30 to 30 (^MD); empty for the printer's setting."))
    label_templates = models.ManyToManyField(
        "inventory.LocationLabelTemplate", verbose_name=_("label templates"), blank=True, related_name="media",
        help_text=_("Only these of their kind for this medium (else those chosen for its label stock); none: "
                    "every template of the medium's size."),
    )
    quality = models.CharField(
        _("print quality"), max_length=16, choices=Quality.choices, default=Quality.STANDARD,
        help_text=_("Preselected in the print dialog. Brother: draft printing or high resolution; "
                    "Zebra: print speed."),
    )
    is_default = models.BooleanField(_("default medium"), default=False)

    def __str__(self):
        return f"{self.printer}: {self.name}"

    def take_from_stock(self):
        """Fill what is empty from the label stock."""
        stock = self.stock
        if stock is None:
            return
        self.name = self.name or str(stock)[:128]
        self.width_mm = self.width_mm or stock.width_mm
        self.height_mm = self.height_mm or stock.height_mm
        self.ptouch_tape = self.ptouch_tape or stock.tape_mm

    def clean(self):
        printer = getattr(self, "printer", None)
        if printer is None:
            return
        self.take_from_stock()
        errors = {}
        if self.stock is not None and self.stock.language != printer.language:
            errors["stock"] = _("These labels are for another kind of printer.")
        if not self.name:
            errors["name"] = _("Name the medium or choose a label stock.")
        if printer.language == Printer.Language.ZPL:
            if not self.width_mm:
                errors["width_mm"] = _("Zebra labels need a width.")
            if not self.height_mm:
                errors["height_mm"] = _("Zebra labels need a height.")
        else:
            if not self.ptouch_tape:
                errors["ptouch_tape"] = _("Choose the tape width.")
            elif printer.model in drivers.PTOUCH_MODELS and \
                    drivers.ptouch_tape(self.ptouch_tape) not in drivers.PTOUCH_MODELS[printer.model].PIN_CONFIGS:
                errors["ptouch_tape"] = _("The printer does not take this tape.")
        if self.zpl_darkness is not None and not -30 <= self.zpl_darkness <= 30:
            errors["zpl_darkness"] = _("Between -30 and 30.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.take_from_stock()
        with transaction.atomic():
            if self.is_default:
                LabelMedium.objects.filter(printer=self.printer_id, is_default=True).exclude(pk=self.pk).update(
                    is_default=False)
            super().save(*args, **kwargs)

    @property
    def is_tape(self):
        return self.printer.language == Printer.Language.PTOUCH

    def chosen_templates(self):
        """The label templates chosen for the medium, else for its label stock (maybe none)."""
        own = self.label_templates.all()
        if own.exists() or self.stock_id is None:
            return own
        return self.stock.label_templates.all()


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
    medium = models.ForeignKey(LabelMedium, verbose_name=_("label medium"), null=True, blank=True,
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
    request_id = models.UUIDField(null=True, blank=True, unique=True, editable=False)
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
        """The outcome in words: the error, or the plain status."""
        return messages.describe(self.code, self.detail) or self.get_status_display()


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
