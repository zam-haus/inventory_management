"""
What a shared link shows in a chat (docs/link-previews.md): the OpenGraph tags of a page, read by link preview bots
of Signal, Matrix, Telegram and others without a login. Pages set `link_preview` in their context to a Preview;
{% link_preview %} (templatetags/link_preview.py) writes the tags, for other pages only the general ones.

Only what guests see anyway, and nothing about people: no notes, teams, names, owners, procurement sources, text
recognised on photos or reasons of disposal, since previews are kept in chats outside the inventory. Photos as
thumbnails, never the original file with its name. Addresses from DEFAULT_URL: behind the proxy the request may not
know it was https.
"""
import html
import re
from dataclasses import dataclass

from django.conf import settings
from django.utils.text import Truncator
from django.utils.translation import gettext as _
from sorl.thumbnail import get_thumbnail

from .templatetags.mytemplatetags import plain_markdown

DESCRIPTION_LENGTH = 200

# Bots fetching a link to show a preview of it (Signal sends WhatsApp's name). Their fetches are not someone
# scanning a label (label_ids/access.py).
PREVIEW_AGENTS = re.compile(
    r"facebookexternalhit|WhatsApp|TelegramBot|Synapse|Slackbot|Discordbot|Twitterbot|Mastodon|LinkedInBot"
    r"|SkypeUriPreview|Iframely|Embedly", re.IGNORECASE)


def is_link_preview(request):
    return bool(PREVIEW_AGENTS.search(request.META.get("HTTP_USER_AGENT", "")))


def absolute(url):
    return url if "://" in url else settings.DEFAULT_URL.rstrip("/") + "/" + url.lstrip("/")


@dataclass
class Image:
    url: str
    width: int
    height: int
    alt: str = ""

    @classmethod
    def thumbnail(cls, field, alt=""):
        """A photo as the galleries show it (the same thumbnail, so mostly made already); None if its file is
        missing (sorl then gives a thumbnail without size)."""
        thumb = get_thumbnail(field, "640x480")
        if not thumb.size:
            return None
        return cls(thumb.url, thumb.width, thumb.height, alt)


@dataclass
class Preview:
    title: str | None = None  # None: the page's <title>, which bots take instead
    description: str = ""
    image: Image | None = None  # None: the logo
    path: str = ""  # the canonical address; "": the page's own


def plain(text, limit=DESCRIPTION_LENGTH):
    """Markdown as plain text (the template escapes it again)."""
    return Truncator(html.unescape(plain_markdown(text))).chars(limit)


def for_item(item):
    images = item.general_images
    return Preview(str(item), plain(item.description) or (item.category.full_name if item.category else ""),
                   Image.thumbnail(images[0].image, str(item)) if images else None, item.get_absolute_url())


def for_unique_item(unique_item, own_images, images):
    """Its item's description, not its notes; disposed ones say so, without why."""
    item = unique_item.item
    description = plain(item.description) or (item.category.full_name if item.category else "")
    if unique_item.is_disposed:
        description = Truncator(f"{_('Disposed.')} {description}".strip()).chars(DESCRIPTION_LENGTH)
    photo = (own_images or images or [None])[0]
    return Preview(str(unique_item), description,
                   Image.thumbnail(photo.image, str(unique_item)) if photo else None, unique_item.get_absolute_url())


def for_location(location):
    path = " › ".join(ancestor.title for ancestor in location.ancestors)
    description = ". ".join(part for part in (path, plain(location.physical_description)) if part)
    image = Image.thumbnail(location.overview_photo, location.title) if location.overview_photo else None
    return Preview(location.title_with_code, Truncator(description).chars(DESCRIPTION_LENGTH), image,
                   location.get_absolute_url())


def for_category(category):
    return Preview(category.name, plain(category.summary) or category.full_name, None, category.get_absolute_url())
