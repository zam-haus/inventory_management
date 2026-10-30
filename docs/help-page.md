# Help page

`/help/` (`inventory/help_views.py`) explains items, locations and unique items to users: bulk or unique, the
label ID, nested locations, location types, what goes where and how to read codes. It is public and linked in the
navbar menu (`question-circle`).

## Content

* The prose is one template per language: `inventory/templates/inventory/help/help_de.html` and `help_en.html`.
  Other languages fall back to German. Change both together.
* The label ID is always `{{ label_id_name }}` (`LABEL_ID_NAME`), never a fixed name.
* From the database, so the page follows the configuration:
  * the location type cards (`_type_cards.html`): grouped by category, code pattern, the type's description,
    facts from its flags (facts all types of a category share are said once for the category), one real code
    as example, and "usually stands in" counted over active locations;
  * the rules under "What goes where" (`_rules.html`), named after the types whose flags they come from.
* The examples (sewing machines, S140, Ka00410, the paint) are made up and stay as they are.

## Links from other pages

`{% help_link "zamid" %}` (`inventory/templatetags/navigation.py`, `help_views.help_link()` in Python) renders a
quiet "More about this" link to one section. The section IDs are fixed in `help_views.ANCHORS`; an unknown one
raises an error. Links are on the item page (unique items), the new-item form (kind), the unique item page (label
ID, missing ID), the location page (code, type properties with the type's description), adding a container and the
label ID lookup.
