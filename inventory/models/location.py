"""Storage locations, their types, label templates and change history."""
from pathlib import Path
from string import Template
import urllib.parse
from uuid import uuid4

from computedfields.models import ComputedFieldsModel, computed
from django.conf import settings
from django.core import validators
from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from paho.mqtt import client as mqttc

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
    moveable = models.BooleanField(_("moveable flag"), default=False)
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
                    "staff status. On the inventory pages only their purpose can be changed; photo, place and "
                    "deletion are locked, what they contain can still be moved."),
    )
    # Fixed types with building-wide codes (shelves, cabinets) can be numbered per room or area.
    area_numbering = models.BooleanField(
        _("number ranges per area"), default=False,
        help_text=_("New locations of this type get a free number from the number range of the room or area "
                    "they are created in, on its page. Only for types with building-wide codes that are not "
                    "moved, with a short name prefix and the numeric sequence."),
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
        if self.area_numbering and (not self.unique or self.moveable or not self.auto_short_name_prefix
                                    or self.auto_sequence != self.Sequence.NUMERIC):
            raise ValidationError({"area_numbering": _(
                "Number ranges per area need building-wide codes, a type that is not moved, a short name "
                "prefix and the numeric sequence.")})

    def numbered_names(self, number):
        """Name and short name for one number, e.g. ("Regal 301", "R301")."""
        return self.generate_names(1, start=str(number))[0]

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

    def free_sublocation_names(self, parent, count):
        """`count` names for new sub-locations of this type in `parent`, skipping codes its children have
        (a shelf with a–d gets e, f, …)."""
        if not self.auto_sequence:
            return []
        taken = set(parent.children.values_list("short_name", flat=True)) if parent.pk else set()
        names = []
        for code in self.sublocation_codes():
            if len(names) == count:
                break
            if code not in taken:
                names.append((f"{self.auto_name_prefix} {code}".strip(), code))
        return names

    def is_valid_start(self, start):
        return bool(self.auto_sequence) and bool(start) and all(char in self.auto_sequence for char in start)

    def free_names(self, count, start):
        """Like generate_names, but skips short names that are taken (by any location of a unique type)."""
        names, number = [], self.str2int(start)
        while len(names) < count:
            batch = self.generate_names(count - len(names), start=self.int2str(number))
            taken = set(Location.objects.filter(type__unique=True, short_name__in=[short for _name, short in batch])
                        .values_list("short_name", flat=True))
            names += [(name, short) for name, short in batch if short not in taken]
            number += len(batch)
        return names

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
    class Meta:
        verbose_name = _("location label template")
        verbose_name_plural = _("location label templates")

    name = models.CharField(_("name"), max_length=128)
    zpl_template = models.TextField(
        _("ZPL template"),
        help_text=_(
            "ZPL2 string, where $url, $unique_identifier, $locatable_identifier and "
            "$descriptive_identifier will be replaced."
        ),
    )
    label_width = models.IntegerField(_("Label width (mm)"))
    label_height = models.IntegerField(_("Label height (mm)"))

    def generate_label_zpl(self, location=None):
        label_code = self.zpl_template
        if location:
            tmpl = Template(label_code)
            label_code = tmpl.safe_substitute(
                url=settings.DEFAULT_URL
                + reverse(
                    "view_location",
                    kwargs={
                        "pk": location.pk,
                        "unique_identifier": location.unique_identifier,
                    },
                ),
                unique_identifier=location.unique_identifier,
                locatable_identifier=location.locatable_identifier,
                descriptive_identifier=location.descriptive_identifier,
            )
        return label_code

    def get_lablary_url(self, location=None):
        return (
            "http://api.labelary.com/v1/printers/8dpmm/labels/"
            + "{:.1f}".format((self.label_width or 0) / 25.4)
            + "x{:.1f}".format((self.label_height or 0) / 25.4)
            + "/0/"
            + urllib.parse.quote(self.generate_label_zpl(location))
        )

    def image_tag(self, location=None):
        return format_html('<img width="100%" src="{}" />', self.get_lablary_url(location))
    image_tag.short_description = "Rendered label"


    def send_to_printer(self, location=None):
        # TODO implement ZPL based replication of labels
        # TODO implement compression
        c = mqttc.Client(**settings.MQTT_CLIENT_KWARGS)
        if settings.MQTT_SERVER_SSL:
            c.tls_set()
        if settings.MQTT_PASSWORD_AUTH:
            c.username_pw_set(**settings.MQTT_PASSWORD_AUTH)
        c.connect(**settings.MQTT_SERVER_KWARGS)
        msg = c.publish(
            settings.MQTT_PRINTER_TOPIC, payload=self.generate_label_zpl(location)
        )
        # Messages to forbidden topics wil be silently ignored! Nothing we can do about it.
        msg.wait_for_publish()
        c.disconnect()

    def __str__(self):
        return self.name


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
        """Numbers used by codes of this type, also outside of any range (e.g. R998)."""
        prefix, numbers = kind.auto_short_name_prefix, []
        for short in Location.objects.filter(type=kind, short_name__startswith=prefix).values_list("short_name", flat=True):
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
        fields = ("purpose", "overview_photo")
        actor = actor or getattr(self, "_history_actor", None)
        with transaction.atomic(using=using):
            previous = None
            if self.pk:
                previous = type(self).objects.using(using).select_for_update().filter(pk=self.pk).values(*fields).first()
            result = super().save(*args, **kwargs)
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
            if self.short_name in unique_locs.values_list("short_name", flat=True):
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
            if self.short_name in sibling_locs.values_list("short_name", flat=True):
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

    def numbering_types(self):
        """Area-numbered location types that can be created here (levels, rooms and areas only), each with the
        location whose range applies, or None while no range applies yet (the first one reserves it)."""
        if not self.type.structure:
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
        # Short names of unique types are unique across all such locations, deleted ones included.
        taken = set(Location.objects.filter(type__unique=True, short_name__in=[short for _name, short in candidates.values()])
                    .values_list("short_name", flat=True))
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
        if self.type.unique:
            return self.short_name
        return self.parent_location.unique_identifier + "." + self.short_name

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

    def label_image_tag(self):
        # Unsaved locations (e.g. an add form re-rendered with errors) have no URL to encode yet.
        if self.pk is None:
            return None
        if self.label_template:
            return self.label_template.image_tag(self)
        elif self.type.default_label_template:
            return self.type.default_label_template.image_tag(self)
        else:
            return None

    label_image_tag.short_description = "Label"

    def get_lablary_url(self):
        if self.label_template:
            return self.label_template.get_lablary_url(self)
        elif self.type.default_label_template:
            return self.type.default_label_template.get_lablary_url(self)
        else:
            return None

    def send_to_printer(self):
        if self.label_template:
            self.label_template.send_to_printer(self)
        elif self.type.default_label_template:
            self.type.default_label_template.send_to_printer(self)

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
