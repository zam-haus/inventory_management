"""Storage locations, their types, label templates and change history."""
from pathlib import Path
from uuid import uuid4

from computedfields.models import ComputedFieldsModel, computed
from django.conf import settings
from django.core import validators
from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.db.models.functions import Upper
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext, gettext_lazy as _

from ..soft_delete import SoftDeleteModel


class LocationType(models.Model):
    class Meta:
        verbose_name = _("location type")
        verbose_name_plural = _("location types")

    name = models.CharField(_("name"), max_length=64, unique=True)
    description = models.TextField(_("description"), blank=True)
    # set if this Locations can not have sublocations (you can not put a box in a box)
    no_sublocations = models.BooleanField(_("no sublocations flag"), default=False)
    # allow this type to be moved from frontend
    moveable = models.BooleanField(
        _("moveable flag"), default=False,
        help_text=_("Locations of this type can be moved on the inventory pages, e.g. boxes, or shelves and cabinets "
                    "(also onto a pallet)."),
    )
    # set if Location.short is to be globally unique
    unique = models.BooleanField(_("unique flag"), default=False)
    # Outside the admin, locations of this type can only be deleted if set (permissions.can_delete_location).
    deletable_in_frontend = models.BooleanField(
        _("deletable outside the admin"), default=False,
        help_text=_("Users with the delete permission may delete locations of this type on the inventory pages, "
                    "e.g. shelves or drawers. Otherwise they can only be deleted in the admin."),
    )
    # Fixed building structure: created, changed and deleted by staff in the admin only (docs/permissions.md).
    admin_only = models.BooleanField(
        _("admin only"), default=False,
        help_text=_("Locations of this type are created, changed and deleted only in the admin, which requires "
                    "staff status. On the inventory pages purpose, description, photo, place and deletion are "
                    "locked; what they contain can still be moved."),
    )
    # Types with building-wide codes (shelves, cabinets) can be numbered per room or area.
    area_numbering = models.BooleanField(
        _("number ranges per area"), default=False,
        help_text=_("New locations of this type get a free number from the number range of the room or area "
                    "they are created in (also on a pallet there), on its page. They keep it when moved. Only for "
                    "types with building-wide codes, a short name prefix and the numeric sequence."),
    )
    # for automatic generation of unique names and short_names:
    auto_name_prefix = models.CharField(
        _("name prefix"), max_length=16, default="", blank=True
    )
    auto_short_name_prefix = models.CharField(
        _("short name prefix"), max_length=4, default="", blank=True
    )
    auto_short_name_padding_length = models.IntegerField(
        _("short name pedding"), default=0
    )
    # Offered with a count when a location of this type is created on the inventory pages (shelves: compartments).
    sublocation_type = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name=_("type of sub-locations"),
        help_text=_("Creating a location of this type on the inventory pages asks how many of these to add "
                    "inside it, e.g. compartments of a shelf."),
    )

    # Numbers are digits only or letters only; older codes from other sequences stay as they are.
    class Sequence(models.TextChoices):
        NUMERIC = "0123456789", _("Numeric (0-9)")
        LOWERCASE = "abcdefghijklmnopqrstuvwxyz", _("Letters lowercase (a-z)")
        UPPERCASE = "ABCDEFGHIJKLMNOPQRSTUVWXYZ", _("Letters uppercase (A-Z)")

    auto_sequence = models.CharField(
        _("sequence"),
        max_length=128,
        choices=Sequence.choices,
        null=True,
        blank=True,
    )

    default_label_template = models.ForeignKey(
        "LocationLabelTemplate",
        limit_choices_to={"subject_type": "location"},
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name=_("default label template"),
    )

    # Fixed building structure (docs/location-structure.md). With the unique flag a location of
    # this type has its own building-wide code; without it, it is a numbered part of its parent.
    class Structure(models.TextChoices):
        LEVEL = "level", _("Building and level")
        ROOM = "room", _("Room")
        AREA = "area", _("Area")

    structure = models.CharField(
        _("building structure"), max_length=8, blank=True, choices=Structure.choices,
        help_text=_("Set for the fixed building structure: building and level, room or area. "
                    "Empty for furniture and containers such as shelves and boxes."),
    )

    # What a location of this type is (docs/location-structure.md): part of the building, a piece of
    # furniture made for storing things (with its compartments), or a container that moves with its contents.
    class Category(models.TextChoices):
        SPACE = "space", _("Space")
        STORAGE_UNIT = "storage_unit", _("Storage unit")
        CONTAINER = "container", _("Container")

    CATEGORY_PLURALS = {
        Category.SPACE: _("Spaces"),
        Category.STORAGE_UNIT: _("Storage units"),
        Category.CONTAINER: _("Containers"),
    }

    category = models.CharField(
        _("location category"), max_length=16, blank=True, choices=Category.choices,
        help_text=_("Space: levels, rooms and areas. Storage unit: furniture for storing things such as shelves, "
                    "cabinets, workbenches with drawers and tool trolleys, with their compartments. Container: "
                    "moves with its contents, such as boxes, cartons and pallets. Empty for anything else, e.g. "
                    "on loan."),
    )

    @classmethod
    def group_by_category(cls, locations):
        """Locations grouped by their type's category, spaces first; those without one come last.

        Returns (category, title, locations) triples; the category is "" for the last group."""
        groups = {}
        for location in locations:
            groups.setdefault(location.type.category, []).append(location)
        order = [*cls.Category.values, ""]
        return [(category, cls.CATEGORY_PLURALS.get(category, _("Other sub-locations")), groups[category])
                for category in order if category in groups]

    def clean(self):
        # A missing category follows from what the type is; a contradicting one is an error.
        if not self.category and self.structure:
            self.category = self.Category.SPACE
        elif not self.category and self.area_numbering:
            self.category = self.Category.STORAGE_UNIT
        if self.structure and self.category != self.Category.SPACE:
            raise ValidationError({"category": _("Types of the building structure are spaces.")})
        if self.area_numbering and self.category != self.Category.STORAGE_UNIT:
            raise ValidationError({"category": _("Number ranges per area are for storage units only.")})
        if self.admin_only and (self.moveable or self.deletable_in_frontend):
            raise ValidationError({"admin_only": _(
                "Locations of an admin-only type can be neither moved nor deleted on the inventory pages.")})
        # Shelves may move (e.g. on a pallet) and keep their number; containers are told apart by their category.
        if self.area_numbering and (not self.unique or not self.auto_short_name_prefix
                                    or self.auto_sequence != self.Sequence.NUMERIC):
            raise ValidationError({"area_numbering": _(
                "Number ranges per area need building-wide codes, a short name prefix and the numeric sequence.")})

    def numbered_names(self, number):
        """Name and short name for one number, e.g. ("Regal 301", "R301")."""
        return self.generate_names(1, start=str(number))[0]

    @classmethod
    def numbered_containers(cls):
        """Container types created on the inventory pages with the next number (boxes, cartons, pallets): building-wide
        codes, a short name prefix and the numeric sequence."""
        return cls.objects.filter(category=cls.Category.CONTAINER, unique=True, admin_only=False,
                                  auto_sequence=cls.Sequence.NUMERIC).exclude(auto_short_name_prefix="").order_by("name")

    def next_free_number(self):
        """(number, name, short name) after the highest number of this type, counting former codes and skipping
        codes that are taken, e.g. (525, "Kiste 525", "K0525"). Old codes of other sequences (K034c) do not count."""
        number = max(LocationNumberRange._taken_numbers(self), default=0) + 1
        while True:
            name, short = self.numbered_names(number)
            if not taken_location_codes([short]):
                return number, name, short
            number += 1

    MAX_SUBLOCATIONS = 100

    def sublocation_codes(self):
        """Codes for sub-locations in order. Letters run on like spreadsheet columns: a … z, aa, ab … az, ba …"""
        sequence, number = self.auto_sequence, 0
        while True:
            number += 1
            if sequence in (self.Sequence.LOWERCASE, self.Sequence.UPPERCASE):
                code, rest = "", number
                while rest:
                    rest, digit = divmod(rest - 1, len(sequence))
                    code = sequence[digit] + code
                yield code
            else:
                yield self.generate_names(1, start=self.int2str(number - 1))[0][1]

    def sublocation_name(self, parent_name, code):
        """The default name of a sub-location of this type: its shelf's or cabinet's name first, "Regal 301 Fach c".
        Too long for the name field, it is only "Fach c"."""
        name = " ".join(part for part in (parent_name, self.auto_name_prefix, code) if part)
        if len(name) > Location._meta.get_field("name").max_length:
            return f"{self.auto_name_prefix} {code}".strip()
        return name

    def free_sublocation_names(self, parent, count):
        """`count` names for new sub-locations of this type in `parent`, skipping codes its children have or had
        (a shelf with a–d gets e, f, …)."""
        if not self.auto_sequence:
            return []
        taken = set()
        if parent.pk:
            taken = set(parent.children.values_list("short_name", flat=True))
            prefix = parent.unique_identifier + "."
            taken.update(code[len(prefix):] for code in LocationFormerCode.objects.filter(code__startswith=prefix)
                         .values_list("code", flat=True) if "." not in code[len(prefix):])
        names = []
        for code in self.sublocation_codes():
            if len(names) == count:
                break
            if code not in taken:
                names.append((self.sublocation_name(parent.name, code), code))
        return names

    def is_valid_start(self, start):
        return bool(self.auto_sequence) and bool(start) and all(char in self.auto_sequence for char in start)

    def free_names(self, count, start):
        """Like generate_names, but skips short names that are taken (by any location of a unique type) or were
        used before (LocationFormerCode)."""
        names, number = [], self.str2int(start)
        while len(names) < count:
            batch = self.generate_names(count - len(names), start=self.int2str(number))
            taken = taken_location_codes(short for _name, short in batch)
            names += [(name, short) for name, short in batch if short not in taken]
            number += len(batch)
        return names

    @property
    def holds_storage_units(self):
        """Shelves and cabinets stand in spaces (the building structure), or on containers that take
        sub-locations (pallets)."""
        return bool(self.structure) or self.category == self.Category.SPACE or (
            self.category == self.Category.CONTAINER and not self.no_sublocations)

    @classmethod
    def holding_storage_units(cls):
        """Filter for locations whose type holds_storage_units."""
        return (~models.Q(type__structure="") | models.Q(type__category=cls.Category.SPACE)
                | models.Q(type__category=cls.Category.CONTAINER, type__no_sublocations=False))

    @property
    def is_coded_structure(self):
        """A level, room or area with its own building-wide code; inherited details stop here."""
        return bool(self.structure) and self.unique

    def int2str(self, i):
        seq = self.auto_sequence
        base = len(seq)
        s = ""
        remainder = int(i)
        while remainder > 0:
            s = seq[remainder % base] + s
            remainder = remainder // base
        if len(s) == 0:
            s = self.auto_sequence[0]
        return s

    def str2int(self, s):
        seq = self.auto_sequence
        base = len(seq)
        i = 0
        for p, c in enumerate(s[::-1]):
            i += base ** p * seq.index(c)
        return i

    def generate_names(self, count, start=None):
        if start is None:
            start = self.auto_sequence[0]

        names = []
        start_int = self.str2int(start)
        for i in range(start_int, start_int + count):
            index = self.int2str(i)
            index_padded = (
                max(0, (self.auto_short_name_padding_length - len(index)))
                * self.auto_sequence[0]
                + index
            )

            names.append(
                (
                    # name
                    self.auto_name_prefix + " " + index,
                    # short_name
                    self.auto_short_name_prefix + index_padded,
                )
            )
        return names

    def __str__(self):
        return self.name


class LocationLabelTemplate(models.Model):
    """A label design (label_printing.design) for locations, items or label IDs; the model's name is kept from
    when templates were ZPL for locations only. Its size comes from the design's first line; names say what is
    on the label, not its size."""

    class Meta:
        verbose_name = _("label template")
        verbose_name_plural = _("label templates")
        # Tape (any length) by width, then labels by width and height
        ordering = ("name", models.F("label_width").asc(nulls_first=True), "label_height")

    class SubjectType(models.TextChoices):
        LOCATION = "location", _("location")
        ITEM = "item", _("bulk item")
        LABEL_ID = "labelid", _("unique item (ZAMid)")

    name = models.CharField(_("name"), max_length=128)
    subject_type = models.CharField(_("labels for"), max_length=16, choices=SubjectType.choices,
                                    default=SubjectType.LOCATION)
    description = models.TextField(_("label description"))
    # The same choices as label_printing.models.Quality
    quality = models.CharField(
        _("print quality"), max_length=16, default="standard",
        choices=[("draft", _("draft (fast)")), ("standard", _("standard")), ("high", _("high quality (slower)"))],
        help_text=_("Its labels are printed in this quality. Brother: draft printing, or twice the resolution along "
                    "the tape; Zebra: print speed."))
    is_active = models.BooleanField(_("active"), default=True,
                                    help_text=_("Only active templates are offered and printed."))
    label_width = models.FloatField(_("width (mm)"), null=True, editable=False,
                                    help_text=_("Empty: as long as the content (Brother tape)."))
    label_height = models.FloatField(_("height (mm)"), null=True, editable=False)

    def design(self):
        """(Design, [Problem]) of the description."""
        from label_printing.design import parse
        return parse(self.description)

    def save(self, *args, **kwargs):
        design, _problems = self.design()
        self.label_width, self.label_height = design.width, design.height
        super().save(*args, **kwargs)

    @property
    def size_text(self):
        if self.label_height is None:
            return "–"
        if self.label_width is None:
            return gettext("height %(height)s mm, any length") % {"height": f"{self.label_height:g}"}
        return f"{self.label_width:g} × {self.label_height:g} mm"

    def __str__(self):
        return f"{self.name} ({self.size_text})"


class LocationAxis(models.Model):
    """A vertical axis of the site: locations in one axis lie roughly above each other."""

    class Meta:
        verbose_name = _("axis")
        verbose_name_plural = _("axes")
        ordering = ("number",)

    number = models.PositiveSmallIntegerField(_("number"), unique=True, help_text=_("Order from left to right."))
    name = models.CharField(_("name"), max_length=64)

    def __str__(self):
        return f"{self.number} {self.name}"


class LocationNumberRange(models.Model):
    """Numbers reserved for locations of one type in a room or area, e.g. its shelves (docs/standortregeln.md)."""

    class Meta:
        verbose_name = _("number range")
        verbose_name_plural = _("number ranges")
        ordering = ("first",)

    location = models.ForeignKey("Location", on_delete=models.CASCADE, related_name="number_ranges",
                                 verbose_name=_("location"))
    type = models.ForeignKey(
        LocationType, on_delete=models.CASCADE, related_name="number_ranges", verbose_name=_("location type"),
        limit_choices_to={"area_numbering": True},
    )
    first = models.PositiveIntegerField(_("from"))
    last = models.PositiveIntegerField(_("to"))

    def clean(self):
        if self.first is not None and self.last is not None and self.first > self.last:
            raise ValidationError({"last": _("The range must not end before it starts.")})

    NEW_SIZE = 20

    @classmethod
    def _taken_numbers(cls, kind):
        """Numbers used by codes of this type, also outside of any range (e.g. R998), or used before."""
        prefix, numbers = kind.auto_short_name_prefix, []
        shorts = [*Location.objects.filter(type=kind, short_name__startswith=prefix).values_list("short_name", flat=True),
                  *LocationFormerCode.objects.filter(code__startswith=prefix).values_list("code", flat=True)]
        for short in shorts:
            if short[len(prefix):].isdigit():
                numbers.append(int(short[len(prefix):]))
        return numbers

    @classmethod
    def suggest(cls, kind, location=None, size=NEW_SIZE):
        """A free range of `size` numbers for `kind` at `location`: in the middle of the largest free gap,
        rounded to tens, so that it and the range before it can grow. Below a location with a range for
        this type, the gap is taken from that range (a reservation within it)."""
        if kind is None:
            return None
        upper = 10 ** (kind.auto_short_name_padding_length or 3) - 1
        ancestors = [node for node in location._self_and_ancestors() if node.pk and node.pk != location.pk] if location else []
        holder = next((node for node in ancestors if node.number_ranges.filter(type=kind).exists()), None)
        bounds = [(r.first, r.last) for r in holder.number_ranges.filter(type=kind)] if holder else [(0, upper)]
        containers = {node.pk for node in ancestors}
        taken = [(r.first, r.last) for r in cls.objects.filter(type=kind).exclude(location_id__in=containers)]
        taken += [(number, number) for number in cls._taken_numbers(kind)]
        gaps = []
        for low, high in bounds:
            start = low
            for first, last in sorted(taken):
                if last < start or first > high:
                    continue
                if first > start:
                    gaps.append((start, first - 1))
                start = max(start, last + 1)
            if start <= high:
                gaps.append((start, high))
        gaps = [gap for gap in gaps if gap[1] - gap[0] + 1 >= size]
        if not gaps:
            return None
        first, last = max(gaps, key=lambda gap: gap[1] - gap[0])
        middle = first + (last - first + 1 - size) // 2
        rounded = middle - middle % 10
        start = rounded if rounded >= first else middle
        return start, start + size - 1

    MAX_RESERVATION = 200

    @classmethod
    def unavailable(cls, kind, first, last):
        """Numbers between first and last that a range of `kind` covers or a code of `kind` uses."""
        covered = set()
        for number_range in cls.objects.filter(type=kind, first__lte=last, last__gte=first):
            covered.update(range(max(first, number_range.first), min(last, number_range.last) + 1))
        covered.update(number for number in cls._taken_numbers(kind) if first <= number <= last)
        return covered

    @classmethod
    def reserve(cls, location, kind, count):
        """Reserve `count` consecutive numbers for `kind` where it is created at `location`: right behind the range
        that applies there if those numbers are free, else as a new range (LocationNumberRange.suggest) at the
        location of that range, or at `location` itself while none applies. Returns the range."""
        source = location.number_range_source(kind)
        target = source or location
        if source is not None:
            last = source.number_ranges.filter(type=kind).order_by("-last").first()
            first, end = last.last + 1, last.last + count
            taken = set(cls._taken_numbers(kind))
            upper = 10 ** (kind.auto_short_name_padding_length or 3) - 1
            if end <= upper and not taken & set(range(first, end + 1)) and \
                    cls.overlap_error(first, end, kind, source, exclude=[last.pk]) is None:
                last.last = end
                last.save()
                return last
        suggestion = cls.suggest(kind, target, size=count)
        if suggestion is None:
            raise ValidationError(_("There is no room for %(count)s more numbers here. Ask the inventory admins.")
                                  % {"count": count})
        return cls.objects.create(location=target, type=kind, first=suggestion[0], last=suggestion[1])

    @classmethod
    def overlap_error(cls, first, last, kind, location, exclude=()):
        """Ranges of one location type must not overlap, unless one lies wholly within a range of a location
        above it: a reservation for a part of that location. Ranges of different types may overlap."""
        above = {node.pk for node in location._self_and_ancestors() if node.pk and node.pk != location.pk}
        others = cls.objects.exclude(pk__in=exclude).filter(first__lte=last, last__gte=first, type=kind)
        for other in others.select_related("location"):
            if other.location_id in above and other.first <= first and last <= other.last:
                continue
            if location.pk and other.first >= first and other.last <= last and other.location_id != location.pk and \
                    location.pk in {node.pk for node in other.location._self_and_ancestors()}:
                continue
            return ValidationError(_("Overlaps the range %(range)s of %(location)s.") % {
                "range": other, "location": other.location.locatable_identifier})
        return None

    def __str__(self):
        return f"{self.first}–{self.last}"


def taken_location_codes(codes):
    """Those of `codes` that are the unique identifier of a location (deleted ones included) or a former code,
    ignoring case (codes differ in more than capital and small letters)."""
    codes = list(codes)
    upper = {code.upper() for code in codes}
    taken = set(Location.objects.annotate(upper=Upper("unique_identifier")).filter(upper__in=upper)
                .values_list("upper", flat=True))
    taken |= set(LocationFormerCode.objects.annotate(upper=Upper("code")).filter(upper__in=upper)
                 .values_list("upper", flat=True))
    return {code for code in codes if code.upper() in taken}


def get_location_overview_upload_path(instance, filename):
    # Every replacement gets its own path so earlier history snapshots stay valid.
    return f"locations/{instance.pk}/overview/{uuid4().hex}{Path(filename).suffix.lower()}"


class Location(SoftDeleteModel, ComputedFieldsModel):
    class Meta:
        verbose_name = _("location")
        verbose_name_plural = _("locations")
        ordering = ("locatable_identifier",)
        # The printable inventory is for members of the local group (granted by migration 0023).
        permissions = [("print_inventory", _("Can print the inventory of locations"))]
        # Codes are found ignoring case (labels hold them in capitals), so they differ in more than that;
        # clean() says so in words (_validate_codes), the database makes sure.
        constraints = [models.UniqueConstraint(Upper("unique_identifier"), name="location_code_unique_ignoring_case")]

    type = models.ForeignKey(LocationType, on_delete=models.PROTECT, verbose_name=_("type"))

    name = models.CharField(
        max_length=128,
        validators=[
            validators.RegexValidator(
                r"[^a-zA-Z0-9 \-()]*",
                message=_("Only numbers, letters and spaces allowed."),
            )
        ],
        verbose_name=_("name"),
    )
    short_name = models.CharField(
        _("short name"),
        max_length=8,
        validators=[
            validators.RegexValidator(
                "[^a-zA-Z0-9]*", message=_("Only numbers and letters allowed.")
            )
        ],
    )

    physical_description = models.TextField(_("physical description"), blank=True)
    # What the location is for, shown with its name ("Box 23: Carp project", see display_name).
    purpose = models.CharField(
        _("purpose"), max_length=50, blank=True,
        validators=[validators.RegexValidator(
            r"[\r\n]", inverse_match=True,
            message=_("The purpose must be a single line."),
        )],
    )
    overview_photo = models.ImageField(
        _("overview photo"), upload_to=get_location_overview_upload_path, blank=True,
    )

    label_template = models.ForeignKey(
        "LocationLabelTemplate",
        limit_choices_to={"subject_type": "location"},
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("label template"),
    )

    parent_location = models.ForeignKey(
        "self",
        related_name="children",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("parent location"),
    )

    # Building structure details (docs/location-structure.md); see the effective_* properties for inheritance.
    axis = models.ForeignKey(
        LocationAxis, on_delete=models.SET_NULL, null=True, blank=True, related_name="locations",
        verbose_name=_("axis"), help_text=_("Set on locations directly below a level; their parts inherit it."),
    )
    fire_load_free = models.BooleanField(
        _("free of fire load"), default=False,
        help_text=_("No combustible materials may be stored here. Applies to everything inside."),
    )
    outdoor = models.BooleanField(_("outdoors"), default=False)
    responsible_teams = models.ManyToManyField(
        "accounts.Team", blank=True, related_name="locations", verbose_name=_("responsible teams"),
    )

    def save(self, *args, actor=None, **kwargs):
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        fields = ("purpose", "overview_photo", "physical_description")
        actor = actor or getattr(self, "_history_actor", None)
        update_fields = kwargs.get("update_fields")

        def saves(*names):
            return update_fields is None or any(name in update_fields for name in names)

        with transaction.atomic(using=using):
            stored = None
            if self.pk:
                stored = type(self).objects.using(using).select_for_update().filter(pk=self.pk).values(
                    *fields, "name", "short_name", "parent_location_id").first()
            # A new short name or parent gives this location (and parts that include its code) new codes;
            # the old ones stay blocked as former codes.
            codes_before = None
            if stored and saves("short_name", "parent_location") and \
                    (stored["short_name"], stored["parent_location_id"]) != (self.short_name, self.parent_location_id):
                codes_before = self._subtree_codes(using)
            result = super().save(*args, **kwargs)
            if codes_before is not None:
                self._keep_former_codes(codes_before, using)
            if stored and saves("name") and stored["name"] != self.name:
                self._rename_default_sublocations(stored["name"], using)
            previous = {field: stored[field] for field in fields} if stored else None
            current = type(self).objects.using(using).values(*fields).get(pk=self.pk)
            # Capture edits from every model save; authored creation also records
            # an initial overview. Unattributed imports keep their existing data.
            if previous is None and actor is not None:
                previous = dict.fromkeys(fields, "")
            if previous is not None and previous != current:
                LocationHistory.objects.using(using).create(
                    location=self, actor=actor,
                    actor_name=actor.get_username() if actor is not None else "",
                    before=previous, after=current,
                )
            return result

    def _subtree_codes(self, using):
        """Unique identifiers of this location and everything below it (deleted ones included), by pk."""
        codes = dict(type(self).objects.using(using).filter(pk=self.pk).values_list("pk", "unique_identifier"))
        pending = [self.pk]
        while pending:
            rows = list(type(self).objects.using(using).filter(parent_location_id__in=pending)
                        .exclude(pk__in=codes).values_list("pk", "unique_identifier"))
            codes.update(rows)
            pending = [pk for pk, _code in rows]
        return codes

    def _keep_former_codes(self, codes_before, using):
        after = dict(type(self).objects.using(using).filter(pk__in=codes_before).values_list("pk", "unique_identifier"))
        former = LocationFormerCode.objects.using(using)
        for pk, code in codes_before.items():
            if after.get(pk, "").upper() != code.upper():  # not when only capital and small letters change
                former.get_or_create(code__iexact=code, defaults={"code": code, "location_id": pk})
        # A location that gets one of its former codes back uses it again.
        for entry in former.annotate(upper=Upper("code")).filter(
                upper__in=[code.upper() for code in after.values()], location_id__in=after):
            if after[entry.location_id].upper() == entry.upper:
                entry.delete()

    def _rename_default_sublocations(self, old_name, using):
        """Parts that still have their default name ("Regal 301 Fach c") follow a new name of this location."""
        sub = self.type.sublocation_type
        if sub is None:
            return
        for part in type(self).objects.using(using).filter(parent_location=self, type=sub):
            if part.name == sub.sublocation_name(old_name, part.short_name):
                part.name = sub.sublocation_name(self.name, part.short_name)
                part.save(using=using)

    def prospective_unique_identifier(self):
        """The unique identifier from the current short name and parent, before saving updates the stored one."""
        if self.type.unique:
            return self.short_name
        return self.parent_location.unique_identifier + "." + self.short_name

    def _validate_codes(self):
        """The location's code (and those of its parts, which change with it) must differ from every other
        location's code in more than capital and small letters. Codes that were used before stay with their
        location: nobody else gets them (LocationFormerCode)."""
        if not self.type.unique and self.parent_location is None:
            return  # reported below
        codes = {self.pk: self.prospective_unique_identifier()}
        stored = Location.objects.filter(pk=self.pk).values("short_name", "parent_location_id").first() if self.pk else None
        if stored and (stored["short_name"], stored["parent_location_id"]) != (self.short_name, self.parent_location_id):
            # Parts without a code of their own (compartments: R301.a) get new codes, too.
            pending = [(self.pk, codes[self.pk])]
            while pending:
                pk, code = pending.pop()
                for child in Location.objects.filter(parent_location_id=pk, type__unique=False).exclude(pk__in=codes):
                    codes[child.pk] = f"{code}.{child.short_name}"
                    pending.append((child.pk, codes[child.pk]))
        owners = {code.upper(): pk for pk, code in codes.items()}
        other = (Location.objects.exclude(pk__in=[pk for pk in codes if pk is not None])
                 .annotate(upper=Upper("unique_identifier")).filter(upper__in=owners).first())
        if other is not None:
            raise ValidationError({"short_name": _(
                "The code %(code)s is too close to %(other)s: codes must differ in more than capital and small "
                "letters.") % {"code": next(code for code in codes.values() if code.upper() == other.upper),
                               "other": other.unique_identifier}})
        for entry in LocationFormerCode.objects.annotate(upper=Upper("code")).filter(upper__in=owners):
            if entry.location_id is None or entry.location_id != owners[entry.upper]:
                raise ValidationError({"short_name": _("The code %(code)s was used before and stays blocked.") % {
                    "code": entry.code}})

    def clean(self):
        if self.is_deleted and self.pk and (
            self.children.filter(is_deleted=False).exists() or self.itemlocation_set.exists()
            or self.unique_items.exists()
        ):
            raise ValidationError({"is_deleted": _("The location is not empty and cannot be deleted.")})
        if not self.is_deleted and self.parent_location and self.parent_location.is_deleted:
            raise ValidationError({"parent_location": _("Deleted locations cannot be used as destinations.")})
        # ensure cycle-free tree
        cur = self
        while cur.parent_location:
            cur = cur.parent_location
            if cur == self:
                raise ValidationError(
                    {"parent_location": _("Location tree may not contain cycles.")}
                )

        # ensure uniqueness on short_name and name per type, if type demands it
        if self.type.unique:
            # get all locations with a LocType defined as unique
            unique_locs = Location.objects.exclude(pk=self.pk).filter(type__unique=True)
            if unique_locs.filter(short_name__iexact=self.short_name).exists():
                raise ValidationError(
                    {"short_name": _("Short name must be unique, as defined by type.")}
                )
            if self.short_name in unique_locs.values_list("name", flat=True):
                raise ValidationError(
                    {"name": _("Name must be unique, as defined by type.")}
                )

        # ensure uniqueness on short_name and name per parent
        if self.parent_location:
            # get all locations with a LocType defined as unique
            sibling_locs = Location.objects.exclude(pk=self.pk).filter(
                parent_location=self.parent_location
            )
            if sibling_locs.filter(short_name__iexact=self.short_name).exists():
                raise ValidationError(
                    {
                        "short_name": _("Short name must be unique among all sibling locations.")
                    }
                )
            if self.short_name in sibling_locs.values_list("name", flat=True):
                raise ValidationError(
                    {"name": _("Name must be unique among all sibling locations.")}
                )

        # ensure that locations without a parent_location are of a unique type
        if not self.parent_location and not self.type.unique:
            raise ValidationError(
                {"parent_location": _("Non-unique locations must have a parent location.")}
            )

        # Shelves and cabinets stand in the building or on a pallet, not in a compartment or another shelf,
        # and never without a place.
        if self.type.area_numbering and (self.parent_location is None
                                         or not self.parent_location.type.holds_storage_units):
            raise ValidationError({"parent_location": _(
                "Locations of type “%(type)s” stand in a level, room or area, or on a pallet.") % {"type": self.type}})

        self._validate_codes()

    @property
    def ancestors(self):
        """Parent locations from the top-level one down to the direct parent."""
        chain, seen, parent = [], {self.pk}, self.parent_location
        while parent is not None and parent.pk not in seen:
            chain.append(parent)
            seen.add(parent.pk)
            parent = parent.parent_location
        return chain[::-1]

    def _self_and_ancestors(self):
        node, seen = self, set()
        while node is not None and node.pk not in seen:
            yield node
            seen.add(node.pk)
            node = node.parent_location

    def _inherited_from(self, has_value):
        """The nearest location from here upwards for which has_value is true.

        Containers and numbered parts take the value of the location they are in, but a room,
        area or level with its own code never inherits: the search ends there.
        """
        for node in self._self_and_ancestors():
            if node.pk and has_value(node):
                return node
            if node.type.is_coded_structure:
                return None
        return None

    @property
    def effective_axis(self):
        return next((node.axis for node in self._self_and_ancestors() if node.axis_id), None)

    @property
    def is_fire_load_free(self):
        return any(node.fire_load_free for node in self._self_and_ancestors())

    @property
    def effective_responsible_teams(self):
        from accounts.models import Team
        source = self._inherited_from(lambda node: node.responsible_teams.exists())
        return source.responsible_teams.all() if source else Team.objects.none()

    def number_range_source(self, location_type):
        """The nearest location from here upwards with a number range for `location_type`. A range applies to
        everything below its location, except the parts that locations below reserve for themselves."""
        return next((node for node in self._self_and_ancestors()
                     if node.pk and node.number_ranges.filter(type=location_type).exists()), None)

    def container_types(self):
        """Container types that can be added here with the next number (LocationType.numbered_containers)."""
        if self.type.no_sublocations:
            return []
        return list(LocationType.numbered_containers())

    def numbering_area(self):
        """The level, room or area whose number ranges apply here: this location, or the one a pallet stands in."""
        return next((node for node in self._self_and_ancestors() if node.type.structure), None)

    def numbering_types(self):
        """Area-numbered location types that can be created here (levels, rooms and areas, and pallets in them),
        each with the location whose range applies, or None while no range applies yet (the first one reserves
        it in the numbering area)."""
        if not self.type.holds_storage_units or self.numbering_area() is None:
            return []
        return [(kind, self.number_range_source(kind))
                for kind in LocationType.objects.filter(area_numbering=True).order_by("name")]

    def _descendant_pks(self):
        pks, pending = set(), [self.pk]
        while pending:
            children = Location.active.filter(parent_location_id__in=pending).values_list("pk", flat=True)
            pending = [pk for pk in children if pk not in pks]
            pks.update(pending)
        return pks

    def free_numbers(self, location_type):
        """Numbers of the applicable ranges that no location of a unique type uses yet, with their names."""
        source = self.number_range_source(location_type)
        if source is None or not location_type.area_numbering:
            return []
        # Parts that locations below the source reserve for themselves are not offered elsewhere.
        reserved = [(r.first, r.last) for r in LocationNumberRange.objects.filter(
            type=location_type, location_id__in=source._descendant_pks())]
        candidates = {}
        for number_range in source.number_ranges.filter(type=location_type):
            for number in range(number_range.first, number_range.last + 1):
                if not any(first <= number <= last for first, last in reserved):
                    candidates[number] = location_type.numbered_names(number)
        # Short names of unique types are unique across all such locations, deleted ones and former codes included.
        taken = taken_location_codes(short for _name, short in candidates.values())
        return [(number, name, short) for number, (name, short) in sorted(candidates.items()) if short not in taken]

    @property
    def purpose_context(self):
        """The purpose to communicate with this location: its own or the one it inherits."""
        source = self._inherited_from(lambda node: bool(node.purpose))
        return source.purpose if source else ""

    @property
    def name_with_short_name(self):
        return f"{self.name} [{self.short_name}]"

    @property
    def display_name(self):
        """The name as pages and lists show it, with the purpose: "Box 23: Carp project"."""
        return f"{self.name}: {self.purpose}" if self.purpose else self.name

    @property
    def path_with_purpose(self):
        """The full path (descriptive_identifier) with the purpose, e.g. for choosing a location."""
        return f"{self.descriptive_identifier}: {self.purpose}" if self.purpose else self.descriptive_identifier

    def validate_deletion(self, *, hard=False, soft_ids=(), hard_ids=()):
        children = self.children.all() if hard else self.children.filter(is_deleted=False)
        excluded = set(hard_ids) if hard else set(soft_ids) | set(hard_ids)
        if children.exclude(pk__in=excluded).exists() or self.itemlocation_set.exists():
            raise ValidationError(_("The location is not empty and cannot be deleted."))
        # Unique items leave the inventory one by one; they are never deleted with their location.
        if self.unique_items.exists():
            raise ValidationError(_("Unique items are still stored here. Move them or remove them from the inventory first."))

    def __str__(self):
        return self.descriptive_identifier

    @computed(
        models.CharField(_("unique identifier"), max_length=64, unique=True),
        depends=[("self", ["short_name"]), ("parent_location", ["unique_identifier"])],
    )
    def unique_identifier(self):
        return self.prospective_unique_identifier()

    @computed(
        models.CharField(_("locatable identifier"), max_length=512, unique=True),
        depends=[
            ("self", ["short_name"]),
            ("parent_location", ["locatable_identifier"]),
        ],
    )
    def locatable_identifier(self):
        if self.parent_location:
            return self.parent_location.locatable_identifier + "." + self.short_name
        return self.short_name

    @computed(
        models.CharField(_("descriptive identifier"), max_length=512),
        depends=[
            ("self", ["name", "short_name"]),
            ("parent_location", ["descriptive_identifier"]),
        ],
    )
    def descriptive_identifier(self):
        if self.parent_location:
            return (
                self.parent_location.descriptive_identifier
                + " "
                + self.name
                + f" [{self.short_name}]"
            )
        return self.name + f" [{self.short_name}]"

    def label_preview_url(self):
        """The location's label (its template, else its type's) as an image (label_printing.views)."""
        template_id = self.label_template_id or self.type.default_label_template_id
        if self.pk is None or template_id is None:
            return None
        return reverse("label_template_preview", args=[template_id, "location", self.pk])

    def label_image_tag(self):
        url = self.label_preview_url()
        return format_html('<img src="{}" alt="" style="max-width: 100%">', url) if url else None

    label_image_tag.short_description = _("label")

    def get_absolute_url(self):
        return reverse(
            "view_location",
            kwargs={"pk": self.pk, "unique_identifier": self.unique_identifier},
        )

    def get_admin_url(self):
        return reverse(
            "admin:inventory_location_change",
            args=(self.pk,),
        )


class LocationFormerCode(models.Model):
    """A unique identifier a location had before (or one of a location deleted for good). It stays blocked so
    that codes on labels and in links never name another location, and it still finds its location."""

    class Meta:
        verbose_name = _("former code")
        verbose_name_plural = _("former codes")
        ordering = ("code",)
        constraints = [models.UniqueConstraint(Upper("code"), name="former_code_unique_ignoring_case")]

    code = models.CharField(_("code"), max_length=64, unique=True)
    location = models.ForeignKey(
        Location, on_delete=models.SET_NULL, null=True, blank=True, related_name="former_codes",
        verbose_name=_("location"), help_text=_("Empty for codes of locations that were deleted for good."),
    )
    created_at = models.DateTimeField(_("date"), default=timezone.now)
    note = models.CharField(_("note"), max_length=200, blank=True)

    def clean(self):
        if self.code and Location.objects.filter(unique_identifier__iexact=self.code).exists():
            raise ValidationError({"code": _("%(code)s is the current code of a location.") % {"code": self.code}})

    def __str__(self):
        return self.code


@receiver(pre_delete, sender=Location)
def block_code_of_deleted_location(sender, instance, using, **kwargs):
    """Deleting a location for good keeps its code blocked (soft deletion keeps the location and its code)."""
    LocationFormerCode.objects.using(using).update_or_create(
        code__iexact=instance.unique_identifier,
        defaults={"code": instance.unique_identifier, "location": None, "note": gettext("deleted")})


class LocationHistory(models.Model):
    class EventType(models.TextChoices):
        OVERVIEW_UPDATED = "overview_updated", _("Overview updated")

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="history", verbose_name=_("location"))
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                              verbose_name=_("user"))
    actor_name = models.CharField(_("user name"), max_length=150, blank=True)
    created_at = models.DateTimeField(_("date"), default=timezone.now, db_index=True)
    event_type = models.CharField(_("event"), max_length=40, choices=EventType.choices, default=EventType.OVERVIEW_UPDATED)
    before = models.JSONField(_("before"), default=dict)
    after = models.JSONField(_("after"), default=dict)

    class Meta:
        ordering = ("-created_at", "-pk")
        default_permissions = ("view",)
        verbose_name = _("location history entry")
        verbose_name_plural = _("location history entries")

    def _photo_url(self, snapshot):
        name = snapshot.get("overview_photo")
        return Location._meta.get_field("overview_photo").storage.url(name) if name else ""

    @property
    def before_photo_url(self):
        return self._photo_url(self.before)

    @property
    def after_photo_url(self):
        return self._photo_url(self.after)
