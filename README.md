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
    `imzam/locale_settings.py`
    Here is a usable template:
    ```
    # SECURITY WARNING: keep this file secret! Do not commit to git!

    DEBUG = True  # for development use only
    ALLOWED_HOSTS = ['127.0.0.1']
    MQTT_PASSWORD_AUTH = dict(username="im.zam.haus-django", password='...')
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
