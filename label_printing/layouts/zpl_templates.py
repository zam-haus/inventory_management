"""The ZPL location label templates of the inventory (LocationLabelTemplate) as layouts for Zebra media."""
from inventory.models import LocationLabelTemplate

from .. import label_urls
from . import Layout, Rendered


class TemplateLayout(Layout):
    subject_type = "location"
    languages = ("zpl",)

    def __init__(self, template):
        self.template = template
        self.key = f"zpl:{template.pk}"
        self.name = template.name

    def supports(self, printer, medium):
        return printer.language in self.languages and medium.templates().filter(pk=self.template.pk).exists()

    def render(self, location, canvas, medium, *, preview=False, user=None):
        zpl = self.template.generate_label_zpl(location)  # $label_url is label_urls.location_url
        return Rendered(zpl=zpl, snapshot=label_urls.location_snapshot(location), label_code=location.unique_identifier)


def template_layouts(subject_type, printer, medium):
    if subject_type != "location" or printer.language != "zpl" or medium is None or medium.pk is None:
        return []
    return [TemplateLayout(template) for template in medium.templates().order_by("name")]


def template_layout(key):
    try:
        return TemplateLayout(LocationLabelTemplate.objects.get(pk=int(key.removeprefix("zpl:"))))
    except (ValueError, LocationLabelTemplate.DoesNotExist):
        raise ValueError(f"unknown layout {key!r}") from None
