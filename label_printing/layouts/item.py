"""Item labels for a drawer or box: name, price and a QR code that opens the item to take some out."""
from django.utils.translation import gettext_lazy as _

from .. import label_urls, render
from ..label_urls import ItemAt
from . import Layout, Rendered, register
from .location import MAX_TAPE_TEXT_MM, qr_or_too_small


@register
class ItemLabel(Layout):
    key = "item"
    name = _("Name, price and QR code")
    subject_type = "item"
    min_height = render.MIN_QR_DOTS

    def render(self, subject: ItemAt, canvas, medium, *, preview=False, user=None):
        code = label_urls.item_label_code(subject, user, create=not preview)
        if code is None:
            code = label_urls.PREVIEW_CODE
        content = label_urls.label_id_content(code)
        price = label_urls.price_text(subject.item)
        footer = " · ".join(part for part in (
            label_urls.display(code), subject.location.unique_identifier if subject.location else "") if part)
        draw = self.tape if canvas.width is None else self.card
        image = draw(subject.item.name, price, footer, content, canvas)
        return Rendered(image=image, snapshot=label_urls.item_snapshot(subject, code), label_code=code)

    def card(self, name, price, footer, content, canvas):
        width, height = canvas.width, canvas.height
        margin = max(2, height // 20)
        qr = qr_or_too_small(content, min(height - 2 * margin, width * 2 // 5), canvas.squeeze)
        image = render.blank(width, height)
        image.paste(qr, (width - margin - qr.width, render.align((height - qr.height) // 2, canvas.squeeze)))
        text_width = width - qr.width - 3 * margin
        inner = height - 2 * margin
        footer_height = inner // 6
        price_height = inner // 4 if price else 0
        name_height = inner - footer_height - price_height - margin
        render.text_box(image, (margin, margin, text_width, name_height), name, weight=700, max_lines=3)
        if price:
            render.text_box(image, (margin, margin + name_height, text_width, price_height), price, weight=700,
                            valign="middle")
        render.text_box(image, (margin, height - margin - footer_height, text_width, footer_height), footer,
                        render.MONO, valign="bottom")
        return image

    def tape(self, name, price, footer, content, canvas):
        height = canvas.height
        qr = qr_or_too_small(content, height, canvas.squeeze)
        gap = max(2, height // 8)
        name_height = height * 11 // 20
        line_height = height - name_height - gap // 2
        bottom = "  ·  ".join(part for part in (price, footer) if part)
        name_font = render.fit_height(name, name_height, weight=700)
        bottom_font = render.fit_height(bottom, line_height)
        text_width = min(max(int(render.text_width(name_font, name)), int(render.text_width(bottom_font, bottom))),
                         canvas.dots(MAX_TAPE_TEXT_MM))
        image = render.blank(qr.width + gap + text_width + gap, height)
        image.paste(qr, (0, render.align((height - qr.height) // 2, canvas.squeeze)))
        left = qr.width + gap
        render.text_box(image, (left, 0, text_width, name_height), name, weight=700, max_lines=2)
        render.text_box(image, (left, height - line_height, text_width, line_height), bottom, valign="bottom")
        return image
