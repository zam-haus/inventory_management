"""Export of the inventory for development databases, safe to publish.

Only reviewed fields leave the database: every exported model lists each of its fields as
kept or replaced, and models not listed at all must be in EXCLUDED_MODELS. A field added
later stops the export until it is reviewed here (see docs/data-export.md).

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
    "auth.permission": "created by migrate",
    "contenttypes.contenttype": "created by migrate",
    "thumbnail.kvstore": "thumbnail cache, rebuilt on demand",
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


# Per model: the fields exported unchanged, the replaced ones (function of the original row),
# and optionally a queryset filter for the exported rows.
EXPORTED_MODELS = {
    "auth.group": {"keep": "name", "replace": {"permissions": current_permissions}},
    "accounts.team": {"keep": "group description code color parent"},
    "inventory.category": {"keep": "name description parent_category full_name"},
    "inventory.barcodetype": {"keep": "name"},
    "inventory.measurementunit": {"keep": "name short description"},
    "inventory.locationlabeltemplate": {"keep": "name zpl_template label_width label_height"},
    "inventory.locationtype": {
        "keep": "name description no_sublocations moveable unique deletable_in_frontend admin_only area_numbering "
                "auto_name_prefix auto_short_name_prefix auto_short_name_padding_length sublocation_type "
                "auto_sequence default_label_template structure category",
    },
    "inventory.locationaxis": {"keep": "number name"},
    "inventory.location": {
        "keep": "is_deleted type name short_name physical_description purpose overview_photo label_template "
                "parent_location axis fire_load_free outdoor unique_identifier locatable_identifier "
                "descriptive_identifier responsible_teams",
    },
    "inventory.locationnumberrange": {"keep": "location type first last"},
    # Codes are public like the locations' own; the note is free text from the admin.
    "inventory.locationformercode": {"keep": "code location created_at", "replace": {"note": emptied}},
    "inventory.locationhistory": {
        "keep": "location created_at event_type before after",
        "replace": {"actor": cleared, "actor_name": redacted_if("actor", "actor_name")},
    },
    "inventory.item": {
        "keep": "is_deleted kind name description category measurement_unit sale_price for_sale "
                "last_purchase_date procurement_source usage_level",
        "replace": {"last_purchase_price": cleared},  # internal
    },
    "inventory.itemlocation": {"keep": "item location amount _order"},
    "inventory.itembarcode": {"keep": "data type item"},
    "inventory.itemimage": {"keep": "image description is_primary item unique_item ocr_text ocr_timestamp"},
    "inventory.itemfile": {
        "keep": "file description internal item unique_item",
        "filter": {"internal": False},  # internal documents: invoices, anything with personal data
    },
    "inventory.stockchange": {
        "keep": "created_at direction reason source item item_name location location_name amount_before "
                "amount_after entry_removed amount is_estimate unit unit_price sale_value request_id",
        "replace": {"actor": cleared, "note": emptied},
    },
    "inventory.uniqueitem": {
        "keep": "item location notes warranty_until purchase_date procurement_source usage_level "
                "responsible_team disposed_at disposal_reason disposal_note",
        "replace": {
            "purchase_price": cleared,  # internal
            "responsible_user": cleared,
            "owner_user": cleared,
            "owner_first_name": redacted_if("owner_user", "owner_first_name", "owner_contact"),
            "owner_contact": emptied,
        },
    },
    "inventory.uniqueitemevent": {
        "keep": "created_at type unique_item from_location from_location_name to_location to_location_name reason",
        "replace": {
            "actor": cleared,
            "note": emptied,
            "from_owner_user": cleared,
            "from_owner_name": redacted_if("from_owner_user", "from_owner_name", "from_owner_contact"),
            "from_owner_contact": emptied,
            "to_owner_user": cleared,
            "to_owner_name": redacted_if("to_owner_user", "to_owner_name", "to_owner_contact"),
            "to_owner_contact": emptied,
        },
    },
    "inventory.labelid": {
        "keep": "status item location unique_item url batch created_at printed_at assigned_at retired_at",
        "replace": {"note": emptied, "created_by": cleared, "assigned_by": cleared, "retired_by": cleared},
    },
}


class UnreviewedData(Exception):
    pass


def serialized_fields(model):
    """The field names Django's serializers write for this model."""
    return {f.name for f in model._meta.local_fields if f.serialize and not f.primary_key} | {
        f.name for f in model._meta.local_many_to_many if f.serialize}


def check_review():
    """Raise UnreviewedData unless every model and field is classified above."""
    problems = []
    for model in apps.get_models():
        label = model._meta.label_lower
        if model._meta.proxy or label in EXCLUDED_MODELS:
            continue
        spec = EXPORTED_MODELS.get(label)
        if spec is None:
            problems.append(f"model {label} is neither exported nor excluded")
            continue
        reviewed = set(spec["keep"].split()) | set(spec.get("replace", {}))
        for name in sorted(serialized_fields(model) - reviewed):
            problems.append(f"field {label}.{name} is not reviewed")
        for name in sorted(reviewed - serialized_fields(model)):
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
        keep, replace = set(spec["keep"].split()), spec.get("replace", {})
        queryset = model._base_manager.filter(**spec.get("filter", {})).order_by("pk")
        for row in serializers.serialize("python", queryset, use_natural_foreign_keys=True,
                                         use_natural_primary_keys=True):
            original = row["fields"]
            if set(original) - keep - set(replace):
                raise UnreviewedData([f"{row['model']}: unreviewed {sorted(set(original) - keep - set(replace))}"])
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
        if row["model"] == "inventory.locationhistory":
            names.update(snapshot.get("overview_photo") for snapshot in (fields["before"], fields["after"])
                         if snapshot.get("overview_photo"))
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
