"""
Database triggers that keep label IDs permanent even against raw SQL and
QuerySet.update(): rows are never deleted, the code never changes, targets are
set only while the row is reserved, and the lifecycle only moves forward.
A claimed ID may lose its target only by becoming retired with no target at all,
which is what deleting the target for good does (LabelId.release_deleted_target).

Migrations pass the target columns that exist at that point in history, so a
later migration that adds a target column calls install() again with the new list.
SQLite drops triggers when Django rebuilds a table, so any migration that alters
inventory_labelid on SQLite must call install() again as well. Migrations from
before the table was renamed pass table=LEGACY_TABLE.
"""
TABLE = "inventory_labelid"
LEGACY_TABLE = "inventory_zamid"  # before migration 0032_label_id
FORWARD_ONLY = (
    "(OLD.status = 'retired' AND NEW.status <> 'retired')"
    " OR (OLD.status = 'assigned' AND NEW.status = 'reserved')"
)


def _relinked(columns, distinct):
    """SQL: a claimed row's target changes other than by being unlinked on retirement."""
    changed = " OR ".join(f"NEW.{c} {distinct} OLD.{c}" for c in columns)
    unlinked = " AND ".join(["NEW.status = 'retired'", *(f"NEW.{c} IS NULL" for c in columns)])
    return f"(OLD.status <> 'reserved' AND ({changed}) AND NOT ({unlinked}))"


def _postgres(columns, table):
    return [
        f"""
        CREATE OR REPLACE FUNCTION label_id_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Label IDs are never deleted' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.code <> OLD.code THEN
                RAISE EXCEPTION 'The code of a label ID cannot change' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF {_relinked(columns, "IS DISTINCT FROM")} THEN
                RAISE EXCEPTION 'The target of a claimed label ID cannot change' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF {FORWARD_ONLY} THEN
                RAISE EXCEPTION 'The lifecycle of a label ID only moves forward' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """,
        f"DROP TRIGGER IF EXISTS label_id_guard_update ON {table}",
        f"DROP TRIGGER IF EXISTS label_id_guard_delete ON {table}",
        f"CREATE TRIGGER label_id_guard_update BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION label_id_guard()",
        f"CREATE TRIGGER label_id_guard_delete BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION label_id_guard()",
    ]


def _sqlite(columns, table):
    return [
        "DROP TRIGGER IF EXISTS label_id_guard_update",
        "DROP TRIGGER IF EXISTS label_id_guard_delete",
        f"""
        CREATE TRIGGER label_id_guard_update BEFORE UPDATE ON {table}
        WHEN NEW.code <> OLD.code OR {_relinked(columns, "IS NOT")} OR {FORWARD_ONLY}
        BEGIN SELECT RAISE(ABORT, 'Label IDs are permanent: code, target and lifecycle cannot be changed back'); END
        """,
        f"""
        CREATE TRIGGER label_id_guard_delete BEFORE DELETE ON {table}
        BEGIN SELECT RAISE(ABORT, 'Label IDs are never deleted'); END
        """,
    ]


def _postgres_drop(table, name):
    return [
        f"DROP TRIGGER IF EXISTS {name}_update ON {table}",
        f"DROP TRIGGER IF EXISTS {name}_delete ON {table}",
        f"DROP FUNCTION IF EXISTS {name}()",
    ]


def _sqlite_drop(table, name):
    return [f"DROP TRIGGER IF EXISTS {name}_update", f"DROP TRIGGER IF EXISTS {name}_delete"]


def _vendor(schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor not in ("postgresql", "sqlite"):
        raise NotImplementedError(f"Label ID triggers are not implemented for {vendor}")
    return vendor


def install(schema_editor, columns, table=TABLE):
    statements = {"postgresql": _postgres, "sqlite": _sqlite}[_vendor(schema_editor)]
    for sql in statements(columns, table):
        schema_editor.execute(sql)


def uninstall(schema_editor, table=TABLE, name="label_id_guard"):
    statements = {"postgresql": _postgres_drop, "sqlite": _sqlite_drop}[_vendor(schema_editor)]
    for sql in statements(table, name):
        schema_editor.execute(sql)


def uninstall_legacy(schema_editor):
    """Drop the triggers of databases migrated before the rename, which were named zamid_guard."""
    uninstall(schema_editor, LEGACY_TABLE, name="zamid_guard")
