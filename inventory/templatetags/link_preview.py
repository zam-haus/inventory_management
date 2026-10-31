"""{% link_preview %}: the OpenGraph tags of every page (inventory/link_preview.py, docs/link-previews.md)."""
from django import template
from django.templatetags.static import static
from django.utils.translation import get_language, to_locale

from .. import link_preview
from ..favicon import favicon_dir

register = template.Library()


@register.inclusion_tag("link_preview.html", takes_context=True)
def link_preview_tags(context):
    preview = context.get("link_preview") or link_preview.Preview()
    request = context.get("request")
    path = preview.path or (request.get_full_path() if request else "/")
    image = preview.image or link_preview.Image(static(f"{favicon_dir()}/icon-maskable-512.png"), 512, 512)
    return {
        "preview": preview, "url": link_preview.absolute(path), "locale": to_locale(get_language() or "de"),
        "image": image, "image_url": link_preview.absolute(image.url),
        # The logo is small: as a small card beside the text, a photo as a big one.
        "card": "summary_large_image" if preview.image else "summary",
    }
