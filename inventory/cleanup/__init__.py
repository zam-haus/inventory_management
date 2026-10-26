"""
Cleanup of item texts and the category tree by outside processing (docs/item-cleanup.md): the admin exports
all items' texts and the category tree as one JSON file (export.py), which also describes the format for
proposals (format.md); the proposals come back as a JSON file, are reviewed change by change and applied
(proposals.py, admin views in admin_views.py).
"""
