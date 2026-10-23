# Raspberry Pi as print agent

A Raspberry Pi with Raspberry Pi OS runs the label print agent (`label_printing/agent.py`,
[label printing](../../docs/label-printing.md)) as a service. It registers itself with the
inventories in its configuration, finds Brother and Zebra printers on its USB ports by itself
and prints their jobs.

## Preparing the SD card

With the card's boot partition mounted on any computer (on a Mac: `/Volumes/boot` or
`/Volumes/bootfs`), from the repository:

```
ops/raspberry-pi/prepare-boot.sh /Volumes/boot https://inventar.zam.haus http://192.0.2.10:8000
```

This copies to `label-agent/` on the boot partition:

| File | What |
|---|---|
| `label_printing/` | the agent (`agent.py`, `devices/`) |
| `config.json` | the servers given (without servers, an existing file is kept) and the intervals |
| `label-agent.service` | systemd service: `python3 -m label_printing.agent`, unprivileged (`DynamicUser`, group `lp` for `/dev/usb/lp*`), restarts on failure |
| `install.sh` | installs the service; added to `cmdline.txt` so the Pi runs it once on its next boot and reboots (like Raspberry Pi Imager's `firstrun.sh`) |
| `update.sh` | copies the code from the boot partition to `/opt/label-agent` on every start of the service |

The Pi needs a network connection to the servers; Python 3 comes with Raspberry Pi OS (3.9 on
bullseye is enough). Works on an installed card as well as on a fresh image (with user, network
and SSH set up as usual, e.g. by Raspberry Pi Imager).

## After the first boot

1. The agent registers with each server. In each inventory: **admin → Label printing → Print
   agents**: activate it (it is named after the Pi's host name).
2. Plug in the printers. They appear under **Printers**, inactive: name them, check model and
   resolution, **Activate**, and add the labels loaded (media, from the label stock).
3. Print a test label (printer list, action **Print a test label**).

## Updating and changing the configuration

Run `prepare-boot.sh` again on the card (or copy files into `/boot/label-agent/` on the Pi) and
restart the service: `sudo systemctl restart label-agent` (or reboot). `config.json` is read on
start; the agent's ID and tokens stay in `/var/lib/label-agent/state.json`.

## On the Pi

| | |
|---|---|
| Status | `systemctl status label-agent` |
| Log | `journalctl -u label-agent -f` |
| Restart | `sudo systemctl restart label-agent` |
| Printers the kernel sees | `ls -l /dev/usb/` |

* **"registration refused (409)"**: the server knows this agent's ID with another token (e.g. a
  newly set up card). Delete the agent in the admin; it registers again.
* **"registration refused (404)"**: the server does not have label printing yet.
* **A printer does not show up**: it must appear as `/dev/usb/lp*` (kernel driver `usblp`). If
  CUPS is installed and has a queue for the printer, remove that queue.
