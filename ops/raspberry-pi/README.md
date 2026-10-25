# Raspberry Pi as print agent

A Raspberry Pi with Raspberry Pi OS runs the label print agent (`label_printing/agent.py`,
[label printing](../../docs/label-printing.md)) as a service. It serves the inventories in its
configuration, each with the token an admin gave it there, finds Brother and Zebra printers on
its USB ports by itself and prints their jobs.

## Creating the agent in the inventory

In each inventory: **admin → Label printing → Print agents → add**, named e.g. after the Pi
(`pi-lager`). Saving shows its token once, as the entry for the configuration:
`{"url": "https://inventar.zam.haus", "token": "…"}`. Lost it? Action **Give a new token**
(the old one stops working).

## Preparing the SD card

With the card's boot partition mounted on any computer (on a Mac: `/Volumes/boot` or
`/Volumes/bootfs`), from the repository, each server with the agent's token from its admin:

```
ops/raspberry-pi/prepare-boot.sh /Volumes/boot https://inventar.zam.haus TOKEN [http://192.0.2.10:8000 TOKEN2]
```

This copies to `label-agent/` on the boot partition:

| File | What |
|---|---|
| `label_printing/` | the agent (`agent.py`, `devices/`) |
| `config.json` | the servers given with their tokens (without servers, an existing file is kept) and the intervals |
| `label-agent.service` | systemd service: `python3 -m label_printing.agent`, unprivileged (`DynamicUser`, group `lp` for `/dev/usb/lp*`), restarts on failure |
| `install.sh` | installs the service; added to `cmdline.txt` so the Pi runs it once on its next boot and reboots (like Raspberry Pi Imager's `firstrun.sh`) |
| `update.sh` | copies the code from the boot partition to `/opt/label-agent` on every start of the service |

The Pi needs a network connection to the servers; Python 3 comes with Raspberry Pi OS (3.9 on
bullseye is enough). Works on an installed card as well as on a fresh image (with user, network
and SSH set up as usual, e.g. by Raspberry Pi Imager).

## After the first boot

1. The agent reports to each server: under **Print agents** it shows as online, with the Pi's
   host name and address.
2. Plug in the printers. They appear under **Printers**, inactive: name them, check model and
   resolution, **Activate**, and add the labels loaded (media, from the label stock).
3. Print a test label (printer list, action **Print a test label**).

## Updating and changing the configuration

Run `prepare-boot.sh` again on the card (or copy files into `/boot/label-agent/` on the Pi) and
restart the service: `sudo systemctl restart label-agent` (or reboot). `config.json` is read on
start.

The tokens are on the card's boot partition, readable by whoever has the card or logs in on the
Pi. A lost card or Pi: deactivate the agent in the admin (or give it a new token).

## On the Pi

| | |
|---|---|
| Status | `systemctl status label-agent` |
| Log | `journalctl -u label-agent -f` |
| Restart | `sudo systemctl restart label-agent` |
| Printers the kernel sees | `ls -l /dev/usb/` |

* **"unknown token"**: the token in `config.json` is not (or no longer) the agent's: create the
  agent in the admin, or give it a new token, and put that into `config.json`.
* **"this agent is deactivated in the admin"**: activate it there.
* **"poll answered 404"**: the server does not have label printing yet.
* **A printer does not show up**: it must appear as `/dev/usb/lp*` (kernel driver `usblp`). If
  CUPS is installed and has a queue for the printer, remove that queue.
