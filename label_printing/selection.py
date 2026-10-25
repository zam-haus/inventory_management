"""
Which label templates are meant for a subject, and which comes first: the rules of each template
(inventory.LabelTemplateRule: a condition over the subject's variables, and the print priority while it holds).
A template is meant for a subject while one of its rules holds; its priority is the highest of those (without
rules: for every subject of its kind, priority 0). The print
dialog preselects the template of the highest priority (a location's: the one it was printed with last,
LastLabel), shows those above 0 and the others on request, unless none ranks higher.
"""
from dataclasses import dataclass

from django.utils import timezone

from inventory.models import LabelId, LabelTemplateRule, LocationLabelTemplate, UniqueItem
from . import label_urls
from .design import texts, variables as design_variables
from .models import LastLabel

# The kinds of templates for a kind of subject: unique items also by their label ID.
KINDS = {"location": ("location",), "item": ("item",), "uniqueitem": ("uniqueitem", "labelid"),
         "labelid": ("labelid",)}
# Subjects whose last label is preselected: a compartment's arrow up or down is up to whoever stuck it on.
REMEMBERED = ("location",)


def subject_for(kind, subject):
    """What a template of `kind` draws for the subject: a unique item's label ID for label ID templates (an
    unsaved stand-in while it has none)."""
    if kind == "labelid" and isinstance(subject, UniqueItem):
        return label_urls.unique_item_label_id(subject) or LabelId(code=label_urls.PREVIEW_CODE)
    return subject


def variables_for(kind, subject):
    """The variables a template of `kind` has for the subject; no label IDs are handed out."""
    subject = subject_for(kind, subject)
    if kind == "location":
        return design_variables.location_variables(subject)
    if kind == "item":
        # Looked up only if a rule asks for the label ID or the QR code (one query per item otherwise)
        return design_variables.item_variables(
            subject, lambda: label_urls.item_label_code(subject, create=False) or label_urls.PREVIEW_CODE)
    if kind == "uniqueitem":
        lid = label_urls.unique_item_label_id(subject)
        return design_variables.unique_item_variables(subject, lid.code if lid else label_urls.PREVIEW_CODE)
    return design_variables.label_id_variables(subject)


def rules_of(templates):
    """{template pk: [(condition, priority)]}, in one query."""
    found = {}
    for rule in LabelTemplateRule.objects.filter(template__in=[template.pk for template in templates]):
        found.setdefault(rule.template_id, []).append((rule.condition, rule.priority))
    return found


def priorities(subject_type, subject, templates, rules=None):
    """{template pk: priority} of those of `templates` meant for the subject (a rule holds, or it has none).
    `rules`: rules_of(templates), read once for many subjects (the print dialog's rows)."""
    variables, found = {}, {}
    rules = rules_of(templates) if rules is None else rules

    def holds(condition, kind):
        if not condition.strip():  # holds for every subject: no variables needed
            return True
        if kind not in variables:  # worked out once per kind, and only for a condition
            variables[kind] = variables_for(kind, subject)
        return texts.holds(condition, variables[kind])

    for template in templates:
        if template.subject_type not in KINDS[subject_type]:
            continue
        if template.pk not in rules:  # without rules: for every subject of its kind, on request
            found[template.pk] = 0
            continue
        holding = [priority for condition, priority in rules[template.pk] if holds(condition, template.subject_type)]
        if holding:
            found[template.pk] = max(holding)
    return found


def meant_for(template, subjects):
    """Those of `subjects` (of the template's kind) the template is meant for; its rules read once."""
    rules = rules_of([template]).get(template.pk)
    if rules is None:  # without rules: every one
        return list(subjects)
    return [subject for subject in subjects
            if any(texts.holds(condition, variables_for(template.subject_type, subject)) for condition, _p in rules)]


def subject_key(subject_type, subject):
    return subject_type, str(subject.pk)


def last_template_pk(subject_type, subject):
    """The template the subject was printed with last, if its last label is remembered."""
    if subject_type not in REMEMBERED or getattr(subject, "pk", None) is None:
        return None
    kind, pk = subject_key(subject_type, subject)
    key = LastLabel.objects.filter(subject_type=kind, subject_pk=pk).values_list("layout_key", flat=True).first()
    return int(key.removeprefix("design:")) if key and key.removeprefix("design:").isdigit() else None


def last_template_pks(subject_type, subjects):
    """{subject pk (str): template pk} of the subjects' last labels, in one query (see last_template_pk)."""
    if subject_type not in REMEMBERED:
        return {}
    keys = [str(subject.pk) for subject in subjects if getattr(subject, "pk", None) is not None]
    found = {}
    for pk, key in LastLabel.objects.filter(subject_type=subject_type, subject_pk__in=keys).values_list(
            "subject_pk", "layout_key"):
        if key and key.removeprefix("design:").isdigit():
            found[pk] = int(key.removeprefix("design:"))
    return found


def remember_label(subject, template, subject_type="location"):
    """The subject was printed with this template (or should be preselected with it)."""
    if subject_type not in REMEMBERED:
        return
    kind, pk = subject_key(subject_type, subject)
    LastLabel.objects.update_or_create(subject_type=kind, subject_pk=pk,
                                       defaults={"layout_key": f"design:{template.pk}", "printed_at": timezone.now()})


def remember_job(job):
    """After a job was printed: its template for each of its subjects whose last label is remembered."""
    if job.subject_type not in REMEMBERED or not job.layout_key.startswith("design:"):
        return
    for entry in job.snapshot:
        if isinstance(entry, dict) and entry.get("type") == job.subject_type and entry.get("id") is not None:
            LastLabel.objects.update_or_create(subject_type=job.subject_type, subject_pk=str(entry["id"]),
                                               defaults={"layout_key": job.layout_key, "printed_at": timezone.now()})


@dataclass
class Ranked:
    outcome: object
    priority: int
    shown: bool = True  # else offered on request ("more labels")
    preselected: bool = False


def rank(outcomes, subject_type, subject, rules=None, last_labels=None):
    """The outcomes (outcomes.py) meant for the subject, the preselected first, then by priority (those that
    can be printed now first among equals), each marked shown or on request. For many subjects, `rules`
    (rules_of) and `last_labels` (last_template_pks) are read once."""
    templates = {outcome.layout.template.pk: outcome.layout.template for outcome in outcomes
                 if getattr(outcome.layout, "template", None) is not None}
    found = priorities(subject_type, subject, list(templates.values()), rules)
    ranked = [Ranked(outcome, found[outcome.layout.template.pk]) for outcome in outcomes
              if getattr(outcome.layout, "template", None) is not None and outcome.layout.template.pk in found]
    ranked.sort(key=lambda entry: (-entry.priority, entry.outcome.target() is None))
    if not ranked:
        return []
    top = ranked[0].priority
    for entry in ranked:
        entry.shown = entry.priority > 0 or entry.priority == top
    last = (last_labels.get(str(subject.pk)) if last_labels is not None and subject_type in REMEMBERED
            else last_template_pk(subject_type, subject))
    chosen = next((entry for entry in ranked if entry.outcome.layout.template.pk == last), ranked[0])
    chosen.preselected = chosen.shown = True
    return [chosen] + [entry for entry in ranked if entry is not chosen]


def preferred_template(subject_type, subject):
    """The template to show the subject's label with outside the print dialog (its page): the one the dialog
    would preselect, else the highest priority among those no printer has labels for; None if none is meant."""
    from . import outcomes

    ranked = rank([outcome for kind in KINDS[subject_type] for outcome in outcomes.outcomes(kind)], subject_type,
                  subject)
    if ranked:
        return ranked[0].outcome.layout.template
    templates = list(LocationLabelTemplate.objects.filter(subject_type__in=KINDS[subject_type], is_active=True))
    found = priorities(subject_type, subject, templates)
    return next(iter(sorted((template for template in templates if template.pk in found),
                            key=lambda template: -found[template.pk])), None)


def best_layout(subject_type, subject, layouts):
    """Of layouts on one printer's labels (layouts_for): the subject's last one, else the highest priority; None
    if none is meant for it."""
    templates = [layout.template for layout in layouts if getattr(layout, "template", None) is not None]
    found = priorities(subject_type, subject, templates)
    meant = [layout for layout in layouts if getattr(layout, "template", None) is not None
             and layout.template.pk in found]
    last = last_template_pk(subject_type, subject)
    return next((layout for layout in meant if layout.template.pk == last), None) or next(
        iter(sorted(meant, key=lambda layout: -found[layout.template.pk])), None)
