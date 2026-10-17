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
* **Stock changes** (sales, purchases, recounts) are logged with who, when and
  why.
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
   ALLOWED_HOSTS = ['localhost', '127.0.0.1', '192.168.178.10', '10.233.1.123']
   SECRET_KEY = "REPLACE ME!!!!!"

   # Django's own login; set True (and the OIDC_* settings) to test the SSO login
   OIDC_ENABLED = False

   # Label IDs: QR codes and the resolver point at this server
   ALLOWED_HOSTS += ['i.localhost', 'id.localhost']
   LABEL_ID_BASE_URL = 'http://i.localhost:8000/'
   LABEL_ID_INVENTORY_BASE = 'http://localhost:8000'

   MQTT_PASSWORD_AUTH = dict(username="im.zam.haus-django", password='...')

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
6. Load the basic dataset: `python manage.py loaddata initial_inventory`
7. Start the local server: `python manage.py runserver`
8. Log in with the **Login** button (Django's own login while `OIDC_ENABLED = False`).

Label IDs resolve locally at `localhost:8000/id/<id>` and, with the settings above,
at `i.localhost:8000/<id>`, which is also what local QR codes and labels contain. The camera scanner needs
HTTPS or `localhost`.

## Deployment

Deployment uses Docker Compose: PostgreSQL, the Django app (`python` service,
which compiles messages, collects static files and runs migrations on start)
and nginx in front of it.

1. Clone this repository.
2. Copy `.env.example` to `.env` and edit at least:
   * `ALLOWED_HOSTS`: the main domains (`inventar.zam.haus`, the label ID hosts);
     other domains are redirected before this check (see [Domains](#domains))
   * `DEFAULT_DOMAIN`: the main address, default `https://inventar.zam.haus` (a bare
     domain means HTTPS)
   * `SECRET_KEY`: a long random string
   * `POSTGRES_PASSWORD`: a random string
   * `MQTT_PASSWORD`: the MQTT password (only needed for printing)
   * `OIDC_RP_CLIENT_ID` and `OIDC_RP_CLIENT_SECRET`: for login via SSO

   For a secure deployment, also consult Django's
   [deployment checklist](https://docs.djangoproject.com/en/stable/howto/deployment/checklist/).
3. Initialize the database and import the initial data:
   ```sh
   docker compose run --rm python ./manage.py migrate
   docker compose run --rm python ./manage.py loaddata initial_inventory
   ```
4. Create a superuser:
   ```sh
   docker compose run --rm python ./manage.py createsuperuser
   ```
5. Start:
   ```sh
   docker compose up -d
   ```

Migrations are applied automatically on every start. Settings for the label ID
resolver hosts and local network detection are described in
[Label IDs](docs/label-ids.md) and [Permissions](docs/permissions.md);
[`.env.example`](.env.example) lists all variables.

### Domains

Every domain name reaching the app is redirected (permanently, keeping path and
query) to its main address (`imzam/canonical_host.py`):

* the inventory to `DEFAULT_DOMAIN` (`https://inventar.zam.haus`), e.g. from the
  earlier `inv.zam.haus`, whose URLs are still on location labels;
* the label ID resolver hosts (`LABEL_ID_RESOLVER_HOSTS`) to `LABEL_ID_RESOLVER_URL`
  (`https://id.zam.haus/`), except label scans: `i.zam.haus/<CODE>` from a QR code
  goes straight on to the inventory, where the scan is recorded with the logged-in user
  (see [Label IDs](docs/label-ids.md)).

Logins (cookies per domain) and the installed app thus always use the main
address. IP addresses, `localhost` and `*.localhost` are never redirected (local
development); `CANONICAL_HOST_REDIRECT=false` turns redirecting off. Scans of the
earlier domains (`DOMAIN_ALIASES`) are still recognised in location fields and by the
camera scanner. New location labels use `DEFAULT_DOMAIN`.
## License

See [LICENSE](LICENSE).
