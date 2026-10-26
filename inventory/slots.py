"""Named places in the inventory's templates where optional apps (e.g. maps) add their parts.

An app registers a template for a slot in its AppConfig.ready(); `{% slot "name" %}` (templatetags/slots.py)
renders the registered templates with the page's context, in the order of registration. Without registrations a
slot renders nothing, so pages stay as they are when an app is not installed.
"""
_slots = {}


def register(name, template_name):
    templates = _slots.setdefault(name, [])
    if template_name not in templates:
        templates.append(template_name)


def unregister(name, template_name):
    if template_name in _slots.get(name, ()):
        _slots[name].remove(template_name)


def templates(name):
    return tuple(_slots.get(name, ()))
