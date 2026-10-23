"""Label ID (ZAMid) labels: the pixel-exact design of inventory/label_ids/labels for Brother tape, and a plain
QR code with the ID for any printer."""
from inventory.label_ids import labels, naming

from .. import label_urls, render
from . import Layout, Rendered, register
from .location import qr_or_too_small

# Printer models → the idlabel profile drawn for their print head (labels.PROFILES).
PROFILE_PRINTERS = {"E550W": "E550W", "P750W": "E550W", "P900": "P900", "P900W": "P900", "P950NW": "P900"}


def snapshot(lid):
    target = lid.target
    return {"type": "labelid", "code": lid.code, "status": lid.status,
            "target": str(lid.url or target or ""), "qr": label_urls.label_id_content(lid.code)}


@register
class LabelIdLabel(Layout):
    """The label ID design as designed: logo, QR code, ID; Brother continuous tape only."""
    key = "labelid"
    subject_type = "labelid"
    languages = ("ptouch",)
    # Pixel-exact in standard resolution (LABEL-ID-SPEC.md §8.2): no high resolution.
    fixed_resolution = True

    @property
    def name(self):
        return naming.name()

    def supports(self, printer, medium):
        return (printer.language in self.languages and not medium.height_mm
                and (PROFILE_PRINTERS.get(printer.model), medium.ptouch_tape) in labels.PROFILES)

    def render(self, lid, canvas, medium, *, preview=False, user=None):
        image = labels.image(lid.code, PROFILE_PRINTERS[medium.printer.model], medium.ptouch_tape)
        return Rendered(image=image, snapshot=snapshot(lid), label_code=lid.code)


@register
class LabelIdPlainLabel(Layout):
    """QR code, ID and the IDs' name; for every printer and label size the QR code fits on."""
    key = "labelid_plain"
    subject_type = "labelid"
    min_height = render.MIN_QR_DOTS

    @property
    def name(self):
        return f"{naming.name()}: QR + ID"

    def render(self, lid, canvas, medium, *, preview=False, user=None):
        content = label_urls.label_id_content(lid.code)
        draw = self.tape if canvas.width is None else self.card
        return Rendered(image=draw(lid.display, content, canvas), snapshot=snapshot(lid), label_code=lid.code)

    def card(self, code, content, canvas):
        width, height = canvas.width, canvas.height
        margin = max(2, height // 20)
        qr = qr_or_too_small(content, min(height - 2 * margin, width // 2), canvas.squeeze)
        image = render.blank(width, height)
        image.paste(qr, (margin, render.align((height - qr.height) // 2, canvas.squeeze)))
        left = margin + qr.width + margin
        text_width, inner = width - left - margin, height - 2 * margin
        render.text_box(image, (left, margin, text_width, inner // 3), naming.name(), valign="bottom")
        render.text_box(image, (left, margin + inner // 3, text_width, inner // 2), code, render.MONO, 700,
                        valign="middle")
        return image

    def tape(self, code, content, canvas):
        height = canvas.height
        qr = qr_or_too_small(content, height, canvas.squeeze)
        gap = max(2, height // 8)
        loaded = render.fit_height(code, height * 3 // 5, render.MONO, 700)
        text_width = int(render.text_width(loaded, code))
        image = render.blank(qr.width + gap + text_width + gap, height)
        image.paste(qr, (0, render.align((height - qr.height) // 2, canvas.squeeze)))
        render.draw_lines(image, (qr.width + gap, 0, text_width, height), loaded, [code], valign="middle")
        return image
