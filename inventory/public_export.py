"""Export of the inventory for development databases, safe to publish.

Every model is either exported (EXPORTED_MODELS) or excluded (EXCLUDED_MODELS); a new model
stops the export until it is listed. Of an exported model, every field is kept except those
listed under "replace". A field that looks personal (a reference to a user account, or a name
with owner, contact, actor, note, email, phone, user, … in it; see looks_personal) stops the
export until it is replaced or, if visitors see it on the website anyway, listed under
"public" (see docs/data-export.md).

Kept is what the website shows to anonymous visitors anyway, plus non-personal internals.
User accounts are not exported; references to them are cleared, recorded names and
contact details replaced.
"""
import io
import json
import os
import re
import shutil
import tarfile
import time
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone

FORMAT_VERSION = 1
REDACTED = "[redacted]"

# Models that are not exported at all, with the reason.
EXCLUDED_MODELS = {
    "accounts.user": "personal data; developers create their own accounts",
    "admin.logentry": "who changed what in the admin",
    "sessions.session": "login sessions",
    "inventory.labelidaccess": "who scanned which label when",
    "inventory.cleanupimport": "uploaded cleanup proposals, who uploaded and applied them",
    "auth.permission": "created by migrate",
    "contenttypes.contenttype": "created by migrate",
    "thumbnail.kvstore": "thumbnail cache, rebuilt on demand",
    "label_printing.printer": "addresses in the local network; each installation sets up its own printers",
    "label_printing.labelmedium": "belongs to the printers",
    "label_printing.printagent": "access tokens of the print agents",
    "label_printing.printjob": "who printed what when",
    "label_printing.lastlabel": "which template each location was printed with last, this installation's history",
    "label_printing.labelstock": "label catalog, filled by migrations; local entries are configuration",
}


def cleared(row):
    return None


def emptied(row):
    return ""


def redacted_if(*fields):
    """The placeholder where any of these fields was set, so that e.g. 'has another owner' stays visible."""
    return lambda row: REDACTED if any(row[f] for f in fields) else ""


def current_permissions(row):
    """Without permissions of removed models, which migrate does not create on import."""
    return [key for key in row["permissions"] if apps.get_containing_app_config(key[1])
            and apps.all_models[key[1]].get(key[2]) is not None]


# Per model: the replaced fields (function of the original row), the fields that look personal but
# are public ("public"), and optionally a queryset filter for the exported rows. Other fields are kept.
EXPORTED_MODELS = {
    "auth.group": {"replace": {"permissions": current_permissions}},
    "accounts.team": {},
    "inventory.category": {},
    "inventory.barcodetype": {},
    "inventory.measurementunit": {},
    "inventory.locationlabeltemplate": {},
    "inventory.labeltemplaterule": {},  # which subjects the templates are meant for
    "label_printing.labelimage": {},  # images for the templates
    "inventory.locationtype": {},
    "inventory.locationaxis": {},
    "inventory.location": {},
    "inventory.locationnumberrange": {},
    # Codes are public like the locations' own; the note is free text from the admin.
    "inventory.locationformercode": {"replace": {"note": emptied}},
    "inventory.item": {"replace": {"last_purchase_price": cleared}},  # internal
    "inventory.itemlocation": {},
    "inventory.itembarcode": {},
    "inventory.itemimage": {},
    "inventory.itemfile": {
        "replace": {},
        "filter": {"internal": False},  # internal documents: invoices, anything with personal data
    },
    "inventory.uniqueitem": {
        "public": "notes disposal_note",  # shown on the unique item's page
        "replace": {
            "purchase_price": cleared,  # internal
            "responsible_user": cleared,
            "owner_user": cleared,
            "owner_first_name": redacted_if("owner_user", "owner_first_name", "owner_contact"),
            "owner_contact": emptied,
        },
    },
    # Who changed something, owners and internal values stay out; so does the name of an internal file.
    "inventory.changelog": {
        "replace": {
            "actor": cleared,
            "actor_name": redacted_if("actor", "actor_name"),
            "note": emptied,
            "changes": lambda row: [change for change in row["changes"]
                                    if not change.get("internal") and not change["field"].startswith("owner")],
            "subject_label": lambda row: REDACTED if row["details"].get("internal") else row["subject_label"],
        },
    },
    "inventory.labelid": {
        "replace": {"note": emptied, "created_by": cleared, "assigned_by": cleared, "retired_by": cleared},
    },
}

# Parts of field names that suggest personal data (or secrets); such fields need a decision above.
PERSONAL_WORDS = ("owner", "contact", "actor", "note", "email", "mail", "phone", "user", "person", "address",
                  "password", "token", "secret")


class UnreviewedData(Exception):
    pass


def publishable(label, field):
    """Whether the export keeps this field as it is: its model is exported and the field not replaced.
    The search finds only such fields (inventory/search/fields.py)."""
    spec = EXPORTED_MODELS.get(label)
    return spec is not None and field not in spec.get("replace", {})


def export_filter(label):
    """The export's filter for the rows of this model, e.g. no internal files; {} for all rows."""
    return dict(EXPORTED_MODELS.get(label, {}).get("filter", {}))


def serialized_fields(model):
    """The field names Django's serializers write for this model."""
    return {f.name for f in model._meta.local_fields if f.serialize and not f.primary_key} | {
        f.name for f in model._meta.local_many_to_many if f.serialize}


def looks_personal(model, name):
    """A reference to a user account, or a name that suggests personal data (PERSONAL_WORDS)."""
    field = model._meta.get_field(name)
    if field.is_relation and field.related_model is not None and \
            field.related_model._meta.label_lower == settings.AUTH_USER_MODEL.lower():
        return True
    name = name.lower()
    return name.endswith("_by") or any(word in name for word in PERSONAL_WORDS)


def check_review():
    """Raise UnreviewedData unless every model is listed above and every field that looks personal is
    replaced or marked public."""
    problems = []
    for model in apps.get_models():
        label = model._meta.label_lower
        if model._meta.proxy or label in EXCLUDED_MODELS:
            continue
        spec = EXPORTED_MODELS.get(label)
        if spec is None:
            problems.append(f"model {label} is neither exported nor excluded")
            continue
        fields = serialized_fields(model)
        reviewed = set(spec.get("public", "").split()) | set(spec.get("replace", {}))
        for name in sorted(fields - reviewed):
            if looks_personal(model, name):
                problems.append(f"field {label}.{name} looks personal: replace it, or mark it public")
        for name in sorted(reviewed - fields):
            problems.append(f"field {label}.{name} no longer exists")
    if problems:
        raise UnreviewedData(problems)


def exported_models():
    models = [apps.get_model(label) for label in EXPORTED_MODELS]
    by_app = {}
    for model in models:
        by_app.setdefault(model._meta.app_config, []).append(model)
    return serializers.sort_dependencies(by_app.items(), allow_cycles=True)


def export_rows():
    check_review()
    rows = []
    for model in exported_models():
        spec = EXPORTED_MODELS[model._meta.label_lower]
        replace = spec.get("replace", {})
        queryset = model._base_manager.filter(**spec.get("filter", {})).order_by("pk")
        for row in serializers.serialize("python", queryset, use_natural_foreign_keys=True,
                                         use_natural_primary_keys=True):
            original = row["fields"]
            row["fields"] = {name: replace[name](original) if name in replace else value
                             for name, value in original.items()}
            rows.append(row)
    return rows


def media_names(rows):
    """Names of the uploaded files the exported rows refer to."""
    file_fields = {}
    for label in EXPORTED_MODELS:
        model = apps.get_model(label)
        file_fields[label] = [f.name for f in model._meta.local_fields if f.get_internal_type() == "FileField"]
    names = set()
    for row in rows:
        fields = row["fields"]
        names.update(fields[name] for name in file_fields[row["model"]] if fields[name])
    return sorted(names)


def iter_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from iter_strings(item)


def possible_personal_data(rows):
    """(model, pk, field, match) where kept text contains a user's name, username or email."""
    terms = set()
    for user in get_user_model()._base_manager.all():
        terms.update(t for t in (user.email, user.username) if len(t or "") >= 5)
        if user.first_name and user.last_name:
            terms.add(f"{user.first_name} {user.last_name}")
    if not terms:
        return []
    pattern = re.compile(r"\b(%s)\b" % "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)),
                         re.IGNORECASE)
    found = []
    for row in rows:
        for name, value in row["fields"].items():
            for text in iter_strings(value):
                match = pattern.search(text)
                if match:
                    found.append((row["model"], row.get("pk"), name, match.group()))
                    break
    return found


def latest_migrations():
    """The newest migration of each app, as the code knows them ("app.name")."""
    return sorted(f"{app}.{name}" for app, name in MigrationLoader(connection).graph.leaf_nodes())


def migration_problem(latest):
    """Why an export made with these latest migrations does not fit this database, or None."""
    loader = MigrationLoader(connection)
    nodes = [tuple(name.split(".", 1)) for name in latest]
    unknown = [f"{app}.{name}" for app, name in nodes if (app, name) not in loader.graph.nodes]
    if unknown:
        return ("The export is from a newer version of the code. Update it (git pull), run migrate, "
                "then import again. Unknown migrations: " + ", ".join(unknown))
    if any(node not in loader.applied_migrations for node in nodes):
        return "Run migrate first."
    return None


def link_or_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def write_export(target, rows, media_root=None):
    """Write data.json, export-info.json and, with media_root, media/ to a directory or, for a
    target ending in .tar, to a tar archive. Returns the names of missing media files."""
    target = Path(target)
    media, missing = [], []
    if media_root is not None:
        for name in media_names(rows):
            source = Path(media_root) / name
            (media if source.is_file() else missing).append((name, source))
    info = {
        "format": FORMAT_VERSION,
        "created_at": timezone.now(),
        "media_included": media_root is not None,
        "media_files": len(media),
        "rows": {label: sum(1 for row in rows if row["model"] == label) for label in EXPORTED_MODELS},
        "excluded": EXCLUDED_MODELS,
        "migrations": latest_migrations(),
    }
    documents = {
        "data.json": json.dumps(rows, cls=DjangoJSONEncoder, indent=1, ensure_ascii=False),
        "export-info.json": json.dumps(info, cls=DjangoJSONEncoder, indent=1),
    }
    if target.suffix == ".tar":
        with tarfile.open(target, "x") as tar:
            for name, text in documents.items():
                data = text.encode()
                member = tarfile.TarInfo(name)
                member.size, member.mtime, member.mode = len(data), int(time.time()), 0o644
                tar.addfile(member, io.BytesIO(data))
            for name, source in media:
                tar.add(source, arcname=f"media/{name}", recursive=False)
    else:
        target.mkdir(parents=True)
        for name, text in documents.items():
            (target / name).write_text(text)
        for name, source in media:
            link_or_copy(source, target / "media" / name)
    return [name for name, _source in missing]
