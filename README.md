# ZAM Inventory Management

The inventory system of the ZAM, running at https://inventar.zam.haus. It is built
for quick and easy data collection without any previous knowledge about the
items: photograph and count what is on a shelf first, annotate later.

* **Locations** form a tree (rooms, shelves, boxes), each with a printed QR
  label, an overview photo and a purpose shown with the name.
* **Items** are either bulk items, counted per location, or unique items:
  single objects such as machines or tools with their own label, owner and
  history.
* **Label IDs** are short, permanent IDs on labels (`K7R-4XD`) whose QR codes lead
  to the item, location or unique item they are attached to. Users see them as
  *ZAMid*; another organization sets its own name with `LABEL_ID_NAME`.
* **Every change** of items, stock and locations, and every printed label, is
  logged; stock changes (sales, purchases, recounts) with why.
* Viewing is public; editing needs an account with the right permissions,
  granted automatically to members who log in on the ZAM network.

Implemented with Django. The full documentation is in [docs/](docs/README.md).

## Development setup

1. Clone this repository:
   `git clone git@github.com:zam-haus/inventory_management.git`
2. Create a local settings file `imzam/local_settings.py`, for example:
   ```python
   # Example local_settings.py for development usage
   # INSECURE, DO NOT USE IN PRODUCTION!
   from pathlib import Path

   DEBUG = True
   TEMPLATE_DEBUG = True
   # Any host reaches the dev server (LAN, i.localhost); none is redirected to DEFAULT_URL
   ALLOWED_HOSTS = ['*']
   CANONICAL_HOST_REDIRECT = False
   SECRET_KEY = "REPLACE ME!!!!!"

   # Django's own login; set True (and the OIDC_* settings) to test the SSO login
   OIDC_ENABLED = False

   # Label IDs: QR codes and the resolver point at this server
   LABEL_ID_BASE_URL = 'http://i.localhost:8000/'
   LABEL_ID_INVENTORY_BASE = 'http://localhost:8000'

   BASE_DIR = Path(__file__).resolve().parent.parent
   DATABASES = {
       "default": {
           "ENGINE": "django.db.backends.sqlite3",
           "NAME": BASE_DIR / "db.sqlite3",
       }
   }
   ```
3. Install the Python requirements (assuming a current Python and pip):
   `pip install -r requirements.dev.txt`
4. Initialize the database: `python manage.py migrate`
5. Create a superuser account: `python manage.py createsuperuser`
6. Load the basic dataset: `python manage.py loaddata initial_inventory`, or instead a copy
   of the real inventory without personal data: `python manage.py import_public_data <export>`
   (see [Data export](docs/data-export.md))
7. Start the local server: `python manage.py runserver`
8. Log in with the **Login** button (Django's own login while `OIDC_ENABLED = False`).

Label IDs resolve locally at `localhost:8000/id/<id>` and, with the settings above,
at `i.localhost:8000/<id>`, which is also what local QR codes and labels contain. The camera scanner needs
HTTPS or `localhost`.

## Deployment

Production runs in containers with `podman-compose` (or Docker Compose): PostgreSQL, the
Django app and nginx in front of it (`docker-compose.yml`). First installation, update,
backup, restore and the other maintenance tasks are described in
[ops/README.md](ops/README.md), with scripts for each in [ops/](ops/). A copy of the
inventory without personal data, for development databases, comes from `ops/export.sh`
([Data export](docs/data-export.md)).

Settings for the label ID resolver hosts and local network detection are described in
[Label IDs](docs/label-ids.md) and [Permissions](docs/permissions.md);
[`.env.example`](.env.example) lists all variables.

### Domains

Every domain name reaching the app is redirected (permanently, keeping path and
query) to its main address (`imzam/canonical_host.py`):

* the inventory to `DEFAULT_URL` (`https://inventar.zam.haus`), e.g. from the
  earlier `inv.zam.haus`, whose URLs are still on location labels;
* the label ID resolver hosts (`LABEL_ID_RESOLVER_HOSTS`) to `LABEL_ID_RESOLVER_URL`
  (`https://id.zam.haus/`), except label scans: `i.zam.haus/<CODE>` from a QR code
  goes straight on to the inventory, where the scan is recorded with the logged-in user
  (see [Label IDs](docs/label-ids.md)).

Logins (cookies per domain) and the installed app thus always use the main
address. IP addresses, `localhost` and `*.localhost` are never redirected (local
development); `CANONICAL_HOST_REDIRECT=false` turns redirecting off. Scans of the
earlier domains (`DOMAIN_ALIASES`) are still recognised in location fields and by the
camera scanner. New location labels use `DEFAULT_URL`.
## License

See [LICENSE](LICENSE).
