"""Location labels: QR code with the location's code, the code white on black, and where it is."""
from django.utils.translation import gettext_lazy as _

from .. import label_urls, render
from . import LabelTooSmall, Layout, Rendered, register

# Tape labels grow with their text up to this length (mm); longer paths get a smaller font.
MAX_TAPE_TEXT_MM = 80


def qr_or_too_small(content, size, step=1):
    image = render.qr_image(render.qr(content), size, step=step)
    if image is None:
        raise LabelTooSmall(content)
    return image


@register
class LocationLabel(Layout):
    key = "location"
    name = _("QR code, code and path")
    subject_type = "location"
    min_height = render.MIN_QR_DOTS

    def render(self, location, canvas, medium, *, preview=False, user=None):
        content = label_urls.location_url(location)
        draw = self.tape if canvas.width is None else self.card
        return Rendered(image=draw(location, content, canvas), snapshot=label_urls.location_snapshot(location),
                        label_code=location.unique_identifier)

    def card(self, location, content, canvas):
        width, height = canvas.width, canvas.height
        margin = max(2, height // 20)
        qr = qr_or_too_small(content, min(height - 2 * margin, width * 9 // 20), canvas.squeeze)
        image = render.blank(width, height)
        image.paste(qr, (margin, render.align((height - qr.height) // 2, canvas.squeeze)))
        left = margin + qr.width + margin
        text_width = width - left - margin
        code_height = (height - 2 * margin) * 2 // 5
        render.inverted_text(image, (left, margin, text_width, code_height), location.unique_identifier)
        render.text_box(image, (left, margin + code_height + margin, text_width, height - code_height - 3 * margin),
                        location.descriptive_identifier, max_lines=4)
        return image

    def tape(self, location, content, canvas):
        height = canvas.height
        qr = qr_or_too_small(content, height, canvas.squeeze)
        gap = max(2, height // 8)
        code_height = height * 11 // 20
        path_height = height - code_height - gap // 2
        code_font = render.fit_height(location.unique_identifier, code_height * 3 // 4, render.MONO, 700)
        code_width = int(render.text_width(code_font, location.unique_identifier)) + 2 * gap
        path_font = render.fit_height(location.descriptive_identifier, path_height)
        max_width = canvas.dots(MAX_TAPE_TEXT_MM)
        text_width = min(max(code_width, int(render.text_width(path_font, location.descriptive_identifier))), max_width)
        image = render.blank(qr.width + gap + text_width + gap, height)
        image.paste(qr, (0, render.align((height - qr.height) // 2, canvas.squeeze)))
        left = qr.width + gap
        render.inverted_text(image, (left, 0, min(code_width, text_width), code_height), location.unique_identifier)
        render.text_box(image, (left, height - path_height, text_width, path_height), location.descriptive_identifier,
                        max_lines=2, valign="bottom")
        return image
