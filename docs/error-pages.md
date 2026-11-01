# Error pages

The inventory's own pages for errors (`inventory/errors.py`), instead of Django's plain ones. They are shown only
with `DEBUG` off; with `DEBUG` on, Django shows its debug pages.

| Status | Page | Offers |
|---|---|---|
| 404 | with the navigation | the search |
| 403 | with the navigation | guests: Login (back to the page); logged in: ask the admins; a reason given with `PermissionDenied` instead |
| 403, failed form check (CSRF) | with the navigation | why it happens (page open too long, login or logout in another tab, cookies blocked), back to the form |
| 400 | standalone | the home page |
| 500 | standalone | try again, the home page, “Report a problem” (when it is set up); says the admins were notified when `ADMINS` is set |

**Standalone** pages share `inventory/standalone_page.html` with the [offline page](installable-app.md): inline
styles and logo, no database, no context processors, so they still work when those are what failed.

On the resolver hosts (`i.zam.haus`, [label IDs](label-ids.md)) every error page stands alone: they serve no inventory
pages to link. Their own answers (unknown ID, typo, retired) come from the resolver page, not from here.

A location that is gone has its own 404 page, with what is known of it ([locations](locations.md#addresses)).
