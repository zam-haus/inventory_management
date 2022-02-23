# ZAM Inventory Managment

This is a basic inventory managment system, with a focus on quick and easy data collection without any previous knowledge about the items in inventory.

To be found at https://im.zam.haus

Implemented with Django.

## Initial Data Collection
1. Define and label all (storage) location
2. Take pictures and count of items in storage locations
   using `/item/create` (i.e., `create_item`, `inventory.views.CreateItemView`) view
3. Annotate items with name, description, category and other metadata.

## Concepts/Features/Requirements/Restrictions
* Items can be at multiple locations
* Item images are the main source of truth during data collection
* Stock changes are not tracked (at the moment)
* Locations are hierarchically structred (tree)
* Label printing relies on Zebra ZPL compatible printers

## Development Setup
To get started do the following:
1. checkout this git repo
    `git clone git@github.com:zam-haus/inventory_management.git`
2. create and edit local settings file
    `imzam/local_settings.py`
    Here is a usable template:
    ```
    # Example local_settings.py for development usage
    # INSECURE, DO NOT USE IN PRODUCTION!
    from pathlib import Path

    DEBUG = True
    TEMPLATE_DEBUG = True
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', '192.168.178.10', '10.233.1.123']
    SECRET_KEY="REPLACE ME!!!!!"

    MQTT_PASSWORD_AUTH = dict(username="im.zam.haus-django", password='...')

    BASE_DIR = Path(__file__).resolve().parent.parent
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
    ```
    for secure deployment: make sure to disable `DEBUG` and set `SECRET_KEY` to a random string and consult https://docs.djangoproject.com/en/4.0/howto/deployment/checklist/.
3. install all python requirements (asuming current python and pip installation is availible)
    `pip install -r requirements.txt`
4. initialize database
    `python manage.py migrate`
5. create superuser account
    `python  manage.py createsuperuser`
6. load basic dataset
    `python manage.py loaddata initial_inventory`
7. start local server
    `python manage.py runserver`

## Label Printing
Print jobs are passed to the printer via MQTT. A simple print server, listening to a (currently) hard-coded topic on mqtt.zam.haus and passing them onto a (currently) hard-coded printer is implemented by `print_server.py`. A more flexible (and complex) solution is planned.


## Deployment

1. clone git repo
2. copy .env.example to .env and edit (atleast) the following variables:
   * `ALLOWED_HOSTS`, set to a domain to be used to access the interface
   * `SECRET_KEY`, set to a long random string
   * `POSTGRES_PASSWORD`, set to a random string
   * `MQTT_PASSWORD`, set to the appropriate password (only needed for printing)
2. import initial data
    ```
    docker-compose run web ./manage.py loaddata initial_inventory
    ```
4. create superuser
    ```
    docker-compose run web ./manage.py createsuperuser
    ```
5. start
    ```
    docker-compose up
    ```

