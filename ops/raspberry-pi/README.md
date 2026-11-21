# Raspberry Pi as print agent

A Raspberry Pi with Raspberry Pi OS (Lite is enough, 64 bit or not) runs the label print agent
(`label_printing/agent.py`, [label printing](../../docs/label-printing.md)) as a service, started on
boot. It serves one inventory, the first server of its configuration, with the token an admin gave it there
(other servers listed there can be chosen on the touch screen for trying things out, until it starts again),
finds Brother and Zebra printers on its USB ports and Brother P-touch printers over Bluetooth by itself
and prints their jobs, several printers at the same time. A display is optional: the **Raspberry Pi Touch
Display** (or another touch screen; see [the touch screen](#the-touch-screen)) shows the jobs, printers and
connections, pauses and aborts jobs, sets a Zebra's labels and ribbon and searches, pairs and unpairs Bluetooth
printers.
With `"read_only": true` the Pi's system runs read-only, to spare the SD card (see [read-only](#read-only)).

## Creating the agent in the inventory

In the inventory: **admin → Label printing → Print agents → add**, named e.g. after the Pi
(`pi-lager`). Saving shows its token once, as the entry for the configuration:
`{"url": "https://inventar.zam.haus", "token": "…"}`. Lost it? Action **Give a new token**
(the old one stops working).

## Preparing the SD card

With the card's boot partition mounted on any computer (on a Mac: `/Volumes/boot` or
`/Volumes/bootfs`), from the repository, the server with the agent's token from its admin (more servers to
choose from on the touch screen may follow; the first is the one the agent works for):

```
ops/raspberry-pi/prepare-boot.sh /Volumes/boot https://inventar.zam.haus TOKEN [http://192.0.2.10:8000 TOKEN2]
```

This copies to `label-agent/` on the boot partition:

| File | What |
|---|---|
| `label_printing/` | the agent (`agent.py`, `panel.py`, `touch.py`, `devices/`) |
| `config.json` | the servers given with their tokens (without servers, an existing file is kept) and the intervals |
| `label-agent.service` | systemd service: `python3 -m label_printing.agent`, as the unprivileged system user `label-agent` (created by `update.sh`; a fixed user, as D-Bus checks the group `bluetooth` of a user it can look up; groups `lp` for `/dev/usb/lp*`, `bluetooth`, `video`/`render`/`input` for the touch screen), writing nowhere but `/run/label-agent`, restarts on failure |
| `label-agent-keep.path`, `label-agent-keep.service`, `keep.sh` | save BlueZ's pairings on the boot partition (`label-agent/bluetooth.tgz`) whenever the agent paired or unpaired a printer |
| `install.sh` | installs the service; added to `cmdline.txt` so the Pi runs it once on its next boot and reboots (like Raspberry Pi Imager's `firstrun.sh`) |
| `update.sh` | on every start of the service: copies the code from the boot partition to `/opt/label-agent`, installs what is missing of `python3-dbus`, `python3-gi`, `bluez`, `libnss-systemd`, `python3-pygame`, `fonts-dejavu-core`, `libegl1`, `libegl-mesa0`, `libgles2`, `libgl1-mesa-dri`, `libopengl0` (and `overlayroot` for read-only) with apt, keeps the service files, the log in RAM (`journald.conf.d/label-agent.conf`) and group `bluetooth`'s access to BlueZ (`/etc/dbus-1/system.d/label-agent-bluetooth.conf`) in place, lets group `video` switch the backlight, puts saved Bluetooth pairings back and switches read-only on or off |

The Pi needs a network connection to the server; Python 3 comes with Raspberry Pi OS (3.9 on
bullseye is enough). Works on an installed card as well as on a fresh image (with user, network
and SSH set up as usual, e.g. by Raspberry Pi Imager, also with its cloud-init files from trixie on).
The packages are installed on the first start with network (the install boot has none); until then the
agent runs without display and Bluetooth, and `systemctl restart label-agent` tries again. With
`"read_only": true` the Pi then reboots once more into the read-only system.

## After the first boot

1. The agent reports to the server: under **Print agents** it shows as online, with the Pi's
   host name and address.
2. Plug in the printers. They appear under **Printers**, inactive: name them, check model and
   resolution (what labels they take is filled in from the model), **Activate**, and mark the label
   material there is as on hand (**Label material**).
3. Print a test label (printer list, action **Print a test label**).

## Bluetooth printers

Brother P-touch printers with Bluetooth (PT-P710BT, PT-P910BT; others named `PT-…BT` are found too,
with the model to choose in the admin) are looked for every `bluetooth_scan_interval` seconds (60). Switch
the printer on and make it visible. A new one is paired:

* with a display (`"bluetooth_pairing": "confirm"`, the default): once confirmed there ("Koppeln?");
* without display, or with `"bluetooth_pairing": "auto"`: by itself.

The agent pairs only with printers it found itself; a phone trying to pair with the Pi is refused.
Paired printers appear in the admin like USB printers (ID `bt-` and the Bluetooth address) and are reached
on RFCOMM channel 1 (`bluetooth_channel`). A printer that is off counts as not reachable; its jobs wait.
`"bluetooth": false` switches Bluetooth off. On the touch screen (tab Bluetooth) printers are also searched for at
once, paired after being declined, and unpaired; else unpairing: `bluetoothctl remove AA:BB:CC:DD:EE:FF`.
Pairings made or removed by the agent are saved on the boot partition (`label-agent/bluetooth.tgz`, with the
pairing keys) and put back on boot, so a read-only Pi keeps them.

## The touch screen

The Raspberry Pi Touch Display (7", 800 × 480, on the DSI connector; the Pi finds it by itself with
`display_auto_detect=1` in `config.txt`, the default) or another screen with touch is used by itself
(`"display": "auto"`; `"touch"`: log an error if there is none; `"none"`).
No desktop is needed: pygame draws straight on the display. Mounted upside down: `"screen_rotation": 180`.

Tabs at the bottom; long pages scroll by dragging:

| Tab | Shows and does |
|---|---|
| Aufträge | what needs someone first (labels to load in a printer, **Sind eingelegt** on a Zebra; a ribbon that does not suit a Zebra's labels, **Farbband wählen**), then each printer's jobs (the one printing with how many labels went out, and the material, e.g. TZe-231) with **Pausieren/Anhalten** or **Fortsetzen**, **Abbrechen** (asks again) and ✕ for a single job; then the jobs waiting for a printer that a printer here could print with the right labels (first which labels to put into which printer, e.g. "18-mm-Band einlegen · P-touch Werkstatt oder Brother PT-P700", then the job), each with its countdown (tap: it waits longer) and ✕; then the last 25 finished jobs (**Erledigt**); a job tapped shows its page with previews of its labels and their counts, and **Nochmal drucken** for a finished one; **Alle anhalten** / **Alle fortsetzen** and **Alle abbrechen** (tap twice). The tab shows how many things need someone. |
| Drucker | the printers with connection (USB, Bluetooth, network) and state (a Brother's tape with its article number), also those the server expects here but not found ("nicht gefunden"); on the card **Etiketten** (Zebra) or **Abschneiden** (Brother: feed and cut, as its cutter button); tap one for its page: state, model, what is loaded (a Zebra's labels with the ribbon set as loaded), its jobs, pause/go on, abort, **Etiketten wählen** and **Farbband wählen** (Zebra), **Testetikett drucken** and **Kalibrieretikett drucken**, and the offsets with − and + (after a calibration label) |
| Verbindung | the server (connected, or why not) and **Stattdessen für … arbeiten** for each other configured server (asks again; until the agent starts again, everything is asked of the new server as after a reboot; not while a printer has jobs), the network addresses, Bluetooth, the agent's name and version, and whether the system is read-only |
| Bluetooth | the printers paired and found, **Drucker suchen**, **Koppeln**, **Entkoppeln** (asks again) |

A Bluetooth printer found asks in a dialog ("Koppeln" / "Nein") until answered. The backlight goes off after
`backlight_timeout` seconds (600) without a touch, unless something prints, waits or asks; the first touch
then only lights it.

Pausing holds a printer: the job being printed stops after the label being sent (a Zebra is also told to
pause after the label it prints, `~PP`) and no other job starts. Aborting a Zebra job clears its buffer
(`~JA`); a Brother prints what it already got. The admin can do the same (print jobs: **Pause**, **Go on**,
**Abort**); the agent gets the command with its next poll.

## Read-only

With `"read_only": true` in `config.json` (the default of `prepare-boot.sh`) the Pi runs read-only: raspi-config's
overlay file system keeps the root file system in RAM, nothing is written to the SD card (the log too stays in
RAM), and a power cut cannot damage it. The boot partition stays writable: `config.json`, the agent's code and the
saved Bluetooth pairings live there, and the agent's code is copied from there on every start as before.

`update.sh` takes care of it on every start of the agent:

* writable and everything installed: switches read-only on (`raspi-config nonint enable_overlayfs`) and reboots;
* read-only, but a package is missing, a service file changed (e.g. after an update with new files) or
  `"read_only": false`: switches read-only off for a reboot, makes the change on the next start and, with
  `"read_only": true`, switches it on again (another reboot).

So updating the agent's code works as before; system updates (`apt upgrade`): set `"read_only": false` (on the
card, or `sudo nano /boot/firmware/label-agent/config.json`), restart the agent (it reboots writable), update,
set it back to `true` and restart. The touch screen's tab Verbindung shows whether the system is read-only.

## Updating and changing the configuration

Over SSH, from the repository: `ops/raspberry-pi/push.sh pi@pi-lager.local` copies the code and service
files into `label-agent/` on the Pi's boot partition (not `config.json`) and restarts the agent. Without
SSH: run `prepare-boot.sh` again on the card (or copy files into `/boot/firmware/label-agent/` on the Pi)
and restart the service: `sudo systemctl restart label-agent` (or reboot). `config.json` is read on
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
| Bluetooth devices | `bluetoothctl devices` |

* **"unknown token"**: the token in `config.json` is not (or no longer) the agent's: create the
  agent in the admin, or give it a new token, and put that into `config.json`.
* **"this agent is deactivated in the admin"**: activate it there.
* **"poll answered 404"**: the server does not have label printing yet.
* **A printer does not show up**: it must appear as `/dev/usb/lp*` (kernel driver `usblp`). If
  CUPS is installed and has a queue for the printer, remove that queue.
* **A Bluetooth printer does not show up**: `bluetoothctl devices` lists what the Pi has seen, `bluetoothctl
  info AA:BB:…` whether it is paired; the log says "no Bluetooth: …" if a package or the adapter is missing.
* **The display stays dark**: the log says "no touch screen: …" with the reason.
