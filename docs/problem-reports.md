# Reporting problems

*Report a problem* (German *Problem melden*, `bug` icon) in the menu of every page sends a technical problem
by mail to the admins: something does not work, shows an error, looks broken or is very slow. Wrong entries
are not meant here; they can be corrected directly.

Nothing is stored in the database: the mail is the report. The code is in `inventory/problem_reports.py`.

## What the admins get

One mail per report to `PROBLEM_REPORT_EMAILS` (comma-separated), by default to the `ADMINS`, through the
SMTP server the error mails use (`EMAIL_HOST`, `EMAIL_PORT`, `SERVER_EMAIL`, `EMAIL_TIMEOUT`). Without any
address the menu entry is not shown and `/problem/` answers 404.

* Subject: `Problem report: <start of the description>`
* The description, the page address, who reported it (user name, or *guest* with the optional contact;
  `, ZAM` from the local network), time, version and browser (user agent)
* What the browser tells about itself: title, previous page, viewport, screen, pixel ratio, language, time
  zone, online, installed app, service worker, whether the screenshot was attached (and how many marks it has),
  what the page shows where it was marked
* What went wrong in the browser tab, the last 20 entries across its pages, oldest first: script errors
  with stack, images, scripts and stylesheets that did not load, requests answered with 400 or more or not
  at all (method, address, status)
* Attachments: `screenshot.jpg`, the picture the user added, and `browser.json` (the browser details as sent)

The version comes from `APP_VERSION`, else the file `VERSION` that `ops/update.sh` writes before building the
image (`git describe`; the image has no `.git`), else `git describe` in a checkout.

## The dialog

`problem_report.js` opens the dialog (`problem_report_modal.html`) and at the same time takes a screenshot of
the visible part of the page as it was before the dialog opened, with
[modern-screenshot](../inventory/static/inventory/vendor/modern-screenshot/README.md), loaded only then. It
copies the page into an SVG and draws that, so it is no pixel copy: camera pictures and canvases stay empty,
and rare CSS can look different. Elements stuck to the screen (the navbar) are put where they are seen. The
user sees the picture and can leave it out, or mark the problem on it: a tap circles a spot, dragging circles an
area (several marks; *Remove marks* starts over). The marks are drawn into `screenshot.jpg`, and the details
say what the page shows there (`marked`: element, its first classes and the start of its text, e.g.
`button.btn.btn-primary "Save"`). A picture of their own (a photo of the screen, a screenshot of the
phone) can be added. Sending stays in the dialog; it thanks or names the problem. Closing it forgets the
report, and the next one takes a new screenshot.

`problem_report_log.js`, the first script in `<head>` (`templates/app_head.html`), notices the errors and
failed requests. It keeps them in `sessionStorage`, so a report on the page after a failed save still has
them.

Without JavaScript the menu entry leads to the page `/problem/` with the same form, without screenshot and
browser details; after sending it goes back to the page the report is about.

## Limits

* Everyone may report, guests too. `PROBLEM_REPORT_LIMIT` reports (default 5) per `PROBLEM_REPORT_WINDOW`
  seconds (default 3600): per account for users, per IP address for guests. Counted in the cache, i.e. per
  worker process: with three gunicorn workers up to three times as many.
* A hidden field (`website`) catches bots; their reports are thanked for and dropped.
* Pictures must be images Pillow can read, at most 10 MB each.
* If the mail server fails, the user is told to try again later and the error is logged (no error mail,
  which would fail as well).
