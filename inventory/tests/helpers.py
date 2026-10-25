"""Shared by several test modules."""
import re


def without_change_log(response):
    """The page without its change log, which names deleted items and locations as history."""
    return re.sub(r'<section class="\w+-panel change-log".*?</section>', "", response.content.decode(), flags=re.S)
