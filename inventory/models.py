from datetime import datetime
from string import Template
import urllib.parse

from paho.mqtt import client as mqttc
from pydoc import describe
from typing_extensions import Required
from xml.etree.ElementTree import Comment
from django.db import models
from django.core import validators
from computedfields.models import ComputedFieldsModel, computed
from django.forms import ValidationError
from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.conf import settings


# Create your models here.

class Item(models.Model):
    # TODO
    # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField("item name", max_length=512, blank=True, null=True)
    description = models.TextField(blank=True)
    # TODO implement signal for automatic adoption by parent_location
    # https://stackoverflow.com/questions/43857902/django-set-foreign-key-to-parent_location-value-on-delete
    category = models.ForeignKey('Category', on_delete=models.SET_NULL, null=True, blank=True)
    measurement_unit = models.ForeignKey('MeasurementUnit', on_delete=models.PROTECT, default=1)
    sale_price = models.DecimalField('sale price per unit', max_digits=8, decimal_places=2, blank=True, null=True, default=None)

    def __str__(self):
        if self.name:
            return self.name
        else:
            return f"Unnamed item {self.pk}"

class Category(models.Model):
    class Meta:
        verbose_name_plural = 'categories'

    name = models.CharField('category name', max_length=512)
    description = models.TextField()
    # TODO implement signal for automatic adoption by parent_location
    # https://stackoverflow.com/questions/43857902/django-set-foreign-key-to-parent_location-value-on-delete
    parent_location = models.ForeignKey(
        'self',
        verbose_name='parent_location cateogry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True)

    def __str__(self):
        return f"Category {self.name}"

def get_item_upload_path(instance, filename):
    return f'items/{instance.item.id}/{datetime.now().isoformat()}_{filename}'

class ItemImage(models.Model):
    image = models.ImageField(
        upload_to=get_item_upload_path)
    description = models.CharField(max_length=512, blank=True)
    item = models.ForeignKey('Item', on_delete=models.CASCADE)

class ItemFile(models.Model):
    file = models.FileField(
        upload_to=get_item_upload_path)
    description = models.CharField(max_length=512, blank=True)
    item = models.ForeignKey('Item', on_delete=models.CASCADE)

class ItemBarcode(models.Model):
    # Enable after inital data cleanup:
    # class Meta:
    #     unique_together = [['data', 'type']]

    data = models.TextField()
    type = models.ForeignKey('BarcodeType', on_delete=models.SET_NULL, null=True, blank=True)
    item = models.ForeignKey('Item', on_delete=models.CASCADE)

    def __str__(self):
        return f"{repr(self.data)} ({self.type})"

class BarcodeType(models.Model):
    name = models.CharField(max_length=128, unique=True)

    def __str__(self):
        return self.name

class MeasurementUnit(models.Model):
    name = models.CharField(max_length=128, unique=True)
    short = models.CharField("unit's abbreviation", max_length=8, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.name} ({self.short})"


class LocationType(models.Model):
    name = models.CharField(max_length=64, unique=True)
    # set if Location.short is to be globally unique
    unique = models.BooleanField(default=False)
    # for automatic generation of unique names and short_names:
    auto_name_prefix = models.CharField(max_length=16, default='', blank=True)
    auto_short_name_prefix = models.CharField(max_length=4, default='', blank=True)
    auto_short_name_padding_length = models.IntegerField(default=0)
    auto_sequence = models.CharField(
        max_length=128,
        choices=[
            ('0123456789', 'Numeric (0-9)'),
            ('abcdefghijklmnopqrstuvwxyz', 'Letters lowercase (a-z)'),
            ('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'Letters lowercase (a-z)'),
            ('0123456789abcdefghijklmnopqrstuvwxyz', 'Alphanumeric lowercase (0-9, a-z)'),
            ('0123456789abcdef', 'Hexadecimal lowercase (0-9, a-f)'),
        ],
        null=True,
        blank=True
    )

    default_label_template = models.ForeignKey(
        'LocationLabelTemplate',
        null=True, blank=True,
        on_delete=models.SET_NULL)

    def int2str(self, i):
        seq = self.auto_sequence
        base = len(seq)
        s = ''
        remainder = int(i)
        while remainder > 0:
            s = seq[remainder % base] + s
            remainder = remainder // base
        if len(s) == 0: s = self.auto_sequence[0]
        return s

    def str2int(self, s):
        seq = self.auto_sequence
        base = len(seq)
        i = 0
        for p, c in enumerate(s[::-1]):
            i += base**p * seq.index(c)
        return i
        
    def generate_names(self, count, start=None):
        if start is None:
            start = self.auto_sequence[0]

        names = []
        start_int = self.str2int(start)
        for i in range(start_int, start_int+count):
            index = self.int2str(i)
            index_padded = max(0, (self.auto_short_name_padding_length - len(index))) * self.auto_sequence[0] + index
            
            names.append((
                # name
                self.auto_name_prefix+' '+index,
                # short_name
                self.auto_short_name_prefix+index_padded
            ))
        return names

    def __str__(self):
        return self.name


class LocationLabelTemplate(models.Model):
    name = models.CharField(max_length=128)
    zpl_template = models.TextField(
        help_text="ZPL2 string, where $url, $unique_identifier, $locatable_identifier and "
                  "$descriptive_identifier will be replaced.")

    def generate_label_zpl(self, location=None):
        label_code = self.zpl_template
        if location:
            tmpl = Template(label_code)
            label_code = tmpl.safe_substitute(
                url=settings.DEFAULT_DOMAIN + reverse(
                    'view_location',
                    kwargs={'pk': location.pk,
                            'unique_identifier': location.unique_identifier}),
                unique_identifier=location.unique_identifier,
                locatable_identifier=location.locatable_identifier,
                descriptive_identifier=location.descriptive_identifier,
            )
        return label_code
    
    def get_lablary_url(self, location=None):
        return 'http://api.labelary.com/v1/printers/8dpmm/labels/2.4x1.2/0/' + \
            urllib.parse.quote(self.generate_label_zpl(location))
    
    def image_tag(self, location=None):
        return mark_safe('<img width="100%%" src="%s" />' % escape(self.get_lablary_url(location)))
    image_tag.short_description = 'Rendered label'

    def send_to_printer(self, location=None):
        c = mqttc.Client(**settings.MQTT_CLIENT_KWARGS)
        c.tls_set()
        c.username_pw_set(**settings.MQTT_PASSWORD_AUTH)
        c.connect(**settings.MQTT_SERVER_KWARGS)
        c.publish('im-label-print-queue/', payload=self.generate_label_zpl(location))

    def __str__(self):
        return self.name


class Location(ComputedFieldsModel):
    type = models.ForeignKey(LocationType, on_delete=models.PROTECT)

    name = models.CharField(
        max_length=128,
        validators=[
            validators.RegexValidator("[^a-zA-Z0-9 \-()]*",
                                      message="Only numbers, letters and spaces allowed.")])
    short_name = models.CharField(
        max_length=8,
        validators=[
            validators.RegexValidator("[^a-zA-Z0-9]*",
                                      message="Only numbers and letters allowed.")])

    description = models.TextField(blank=True)

    label_template = models.ForeignKey('LocationLabelTemplate', on_delete=models.SET_NULL, null=True, blank=True)
    
    parent_location = models.ForeignKey(
        'self', related_name='children', on_delete=models.SET_NULL, null=True, blank=True)

    def clean(self):
        # ensure cycle-free tree
        cur = self
        while cur.parent_location:
            cur = cur.parent_location
            if cur == self:
                raise ValidationError({'parent_location': 'Location tree may not contain cycles.'})

        # ensure uniqueness on short_name and name per type, if type demands it
        if self.type.unique:
            # get all locations with a LocType defined as unique
            unique_locs = Location.objects.exclude(pk=self.pk).filter(type__unique=True)
            if self.short_name in unique_locs.values_list('short_name', flat=True):
                raise ValidationError({'short_name': 'Short name must be unique, as defined by type.'})
            if self.short_name in unique_locs.values_list('name', flat=True):
                raise ValidationError({'name': 'Name must be unique, as defined by type.'})

        # ensure uniqueness on short_name and name per parent
        if self.parent_location:
            # get all locations with a LocType defined as unique
            sibling_locs = Location.objects.exclude(pk=self.pk).filter(parent_location=self.parent_location)
            if self.short_name in sibling_locs.values_list('short_name', flat=True):
                raise ValidationError({'short_name': 'Short name must be unique among all sibling locations.'})
            if self.short_name in sibling_locs.values_list('name', flat=True):
                raise ValidationError({'name': 'Name must be unique among all sibling locations.'})

        # ensure that locations without a parent_location are of a unique type
        if not self.parent_location and not self.type.unique:
            raise ValidationError({'parent_location': 'Non-unique locations must have a parent location.'})

    def __str__(self):
        return self.descriptive_identifier

    @computed(models.CharField(max_length=64, unique=True), depends=[
        ('self', ['short_name']), ('parent_location', ['unique_identifier'])])
    def unique_identifier(self):
        if self.type.unique:
            return self.short_name
        return self.short_name + '.' + self.parent_location.unique_identifier

    @computed(models.CharField(max_length=512, unique=True), depends=[
        ('self', ['short_name']), ('parent_location', ['locatable_identifier'])])
    def locatable_identifier(self):
        if self.parent_location:
            return self.short_name + '.' + self.parent_location.locatable_identifier
        return self.short_name
    
    @computed(models.CharField(max_length=512), depends=[
        ('self', ['name', 'short_name']), ('parent_location', ['descriptive_identifier'])])
    def descriptive_identifier(self):
        if self.parent_location:
            return self.name + f' [{self.short_name}] ' + self.parent_location.descriptive_identifier
        return self.name + f' [{self.short_name}]'
    
    def label_image_tag(self):
        if self.label_template:
            return self.label_template.image_tag(self)
        elif self.type.default_label_template:
            return self.type.default_label_template.image_tag(self)
        else:
            return None
    label_image_tag.short_description = 'Label'

    def send_to_printer(self):
        if self.label_template:
            self.label_template.send_to_printer(self)
        elif self.type.default_label_template:
            self.type.default_label_template.send_to_printer(self)


class ItemLocation(models.Model):
    class Meta:
        unique_together = ['item', 'location']

    item = models.ForeignKey('Item', on_delete=models.CASCADE)
    location = models.ForeignKey(
        'Location',
        on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=16, decimal_places=3)

    def __str__(self):
        return f"{self.amount} {self.item.measurement_unit} @ {self.location}"
