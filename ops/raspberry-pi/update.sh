#!/bin/sh
# Runs as root before every start of the agent (label-agent.service): copies the agent's code from the
# boot partition (Raspberry Pi OS: /boot, from bookworm on /boot/firmware), installs what the display, the touch
# screen and Bluetooth need, and keeps the system read-only if config.json says so ("read_only": true).
# Nothing here may stop the agent from starting: without the packages it runs without display and Bluetooth, and
# the next start tries again.
#
# Read-only: raspi-config's overlay file system keeps the root file system in RAM (nothing written to the SD
# card; the boot partition stays writable for config.json and the Bluetooth pairings). Changes to the system
# (packages, the service's files) are made with the overlay off: when one is needed, this script switches it off
# and reboots, makes the change on the next start and switches it on again (another reboot).
boot=""
for candidate in /boot/firmware /boot; do
    if [ -d "$candidate/label-agent/label_printing" ]; then boot=$candidate; break; fi
done
agent=/opt/label-agent
if [ -n "$boot" ]; then
    rm -rf $agent/label_printing.new
    cp -r "$boot/label-agent/label_printing" $agent/label_printing.new
    find $agent/label_printing.new -name '._*' -delete  # macOS leaves these on FAT
    rm -rf $agent/label_printing
    mv $agent/label_printing.new $agent/label_printing
    for file in update.sh keep.sh; do
        [ -f "$boot/label-agent/$file" ] && cp "$boot/label-agent/$file" "$agent/$file.new" && mv "$agent/$file.new" "$agent/$file"
    done
else
    echo "label-agent: no label-agent/ on the boot partition, keeping the installed code" >&2
fi

setting() {  # a value of config.json (true/false/text), or the default
    [ -n "$boot" ] && python3 -c 'import json, sys
try:
    value = json.load(open(sys.argv[1])).get(sys.argv[2], sys.argv[3])
except Exception:
    value = sys.argv[3]
print(str(value).lower() if isinstance(value, bool) else value)' "$boot/label-agent/config.json" "$1" "$2" 2>/dev/null || echo "$2"
}
read_only=$(setting read_only false)
overlay_now=no; grep -q "overlayroot=tmpfs" /proc/cmdline && overlay_now=yes
overlay_set=no; [ -n "$boot" ] && grep -q "overlayroot=tmpfs" "$boot/cmdline.txt" && overlay_set=yes

# The PiFace Control & Display (python3-spidev, SPI on in config.txt), the touch screen (python3-pygame, DejaVu
# fonts; SDL's KMS driver draws even in 2D through OpenGL: Mesa's EGL, the GPU's driver (libgl1-mesa-dri) and
# # glvnd's libOpenGL, all only recommended, not dependencies; without them the screen stays black), Bluetooth
# printers (BlueZ on D-Bus) and, for read-only, raspi-config's overlay (overlayroot).
packages="python3-spidev python3-dbus python3-gi bluez python3-pygame fonts-dejavu-core libegl1 libegl-mesa0 libgles2 libgl1-mesa-dri libopengl0"
[ "$read_only" = true ] && packages="$packages overlayroot"
missing=""
for package in $packages; do
    dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q "install ok installed" || missing="$missing $package"
done

# Files of the system this script keeps as they should be: "source target" (sources here or on the boot partition)
policy_file=$agent/label-agent-bluetooth.conf
cat > $policy_file <<'POLICY'
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<!-- label print agent (label_printing/devices/bluetooth.py): looks for, pairs and lists printers -->
<busconfig>
  <policy group="bluetooth">
    <allow send_destination="org.bluez"/>
  </policy>
</busconfig>
POLICY
journal_file=$agent/journald-label-agent.conf
cat > $journal_file <<'JOURNAL'
# label print agent (ops/raspberry-pi/update.sh): the log in RAM only, never on the SD card
[Journal]
Storage=volatile
RuntimeMaxUse=32M
JOURNAL
files="$policy_file /etc/dbus-1/system.d/label-agent-bluetooth.conf
$journal_file /etc/systemd/journald.conf.d/label-agent.conf"
for unit in label-agent.service label-agent-keep.path label-agent-keep.service; do
    [ -n "$boot" ] && [ -f "$boot/label-agent/$unit" ] && files="$files
$boot/label-agent/$unit /etc/systemd/system/$unit"
done
outdated=""
outdated_files() {
    echo "$files" | while read -r source target; do
        cmp -s "$source" "$target" || echo "$target"
    done
}
outdated=$(outdated_files)

# The service's user, member of the groups it uses (D-Bus checks group bluetooth in /etc/group, not the
# service's SupplementaryGroups)
groups="lp spi gpio bluetooth video input render"
user_ok=yes
for group in $groups; do
    id -nG label-agent 2>/dev/null | tr ' ' '\n' | grep -qx "$group" || user_ok=no
done

if [ $overlay_now = yes ]; then
    # Read-only now: what needs changing waits for a start with the overlay off
    if [ "$read_only" != true ] || [ -n "$missing" ] || [ -n "$outdated" ] || [ $user_ok = no ]; then
        echo "label-agent: switching read-only off for a reboot (read_only: $read_only, missing:$missing, outdated: $(echo $outdated))"
        raspi-config nonint disable_overlayfs && systemctl --no-block reboot
        exit 0
    fi
else
    if [ $overlay_set = yes ] && [ "$read_only" != true ]; then  # set, but not active yet
        raspi-config nonint disable_overlayfs
    fi
    # The groups and the user first: systemd looks the service's user up even to run this script
    for group in $groups; do
        getent group "$group" >/dev/null || groupadd --system "$group"
    done
    if [ $user_ok = no ]; then
        id label-agent >/dev/null 2>&1 || useradd --system --user-group --no-create-home --home-dir /nonexistent \
            --shell /usr/sbin/nologin --comment "label print agent" label-agent
        usermod -a -G "$(echo $groups | tr ' ' ',')" label-agent && echo "label-agent: user label-agent in groups $groups"
    fi
    if [ -n "$missing" ]; then
        echo "label-agent: installing$missing"
        export DEBIAN_FRONTEND=noninteractive
        apt-get install -y --no-install-recommends $missing \
            || { apt-get update && apt-get install -y --no-install-recommends $missing; } \
            || echo "label-agent: could not install$missing (no network?); trying again on the next start" >&2
    fi
    mkdir -p /etc/systemd/journald.conf.d
    reload=no
    for target in $outdated; do
        source=$(echo "$files" | awk -v target="$target" '$2 == target {print $1}')
        cp "$source" "$target"
        echo "label-agent: updated $target"
        case $target in
            */dbus-1/*) systemctl reload dbus 2>/dev/null || true ;;
            */journald.conf.d/*) systemctl restart systemd-journald 2>/dev/null || true ;;
            */systemd/system/*) reload=yes ;;
        esac
    done
    if [ $reload = yes ] && [ -z "$INSTALLING" ]; then  # (install.sh enables the service itself, then reboots)
        # Service files changed: systemd reloads them and starts the agent again with them, a moment after this
        # start (a daemon-reload from within it would end it); read-only waits for that next start
        echo "label-agent: service files changed, starting again with them"
        systemd-run --quiet --on-active=3 --unit="label-agent-reload-$(date +%s)" /bin/sh -c \
            "systemctl daemon-reload; systemctl enable label-agent-keep.path; systemctl restart label-agent.service"
        exit 0
    fi
fi
# The touch screen's backlight: group video may switch it (sysfs, so again on every boot)
for power in /sys/class/backlight/*/bl_power; do
    [ -e "$power" ] && chgrp video "$power" && chmod g+w "$power"
done
# Bluetooth pairings saved on the boot partition (keep.sh): back once per boot, before the agent starts
if [ -n "$boot" ] && [ -f "$boot/label-agent/bluetooth.tgz" ] && [ ! -e /run/label-agent-bluetooth-restored ]; then
    if tar -xzf "$boot/label-agent/bluetooth.tgz" -C /var/lib; then
        echo "label-agent: Bluetooth pairings restored"
        systemctl restart bluetooth.service 2>/dev/null || true
    fi
    touch /run/label-agent-bluetooth-restored
fi
if command -v rfkill >/dev/null; then rfkill unblock bluetooth 2>/dev/null || true; fi
systemctl enable --now bluetooth.service 2>/dev/null || true
systemctl start label-agent-keep.path 2>/dev/null || true

# Read-only from now on, once everything is in place (another reboot)
missing_now=""
for package in $packages; do
    dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q "install ok installed" || missing_now="$missing_now $package"
done
if [ "$read_only" = true ] && [ $overlay_now = no ] && [ -z "$INSTALLING" ] && [ -z "$missing_now" ] \
        && [ -z "$(outdated_files)" ]; then
    if [ $overlay_set = yes ]; then  # set before, yet the system came up writable: no reboot loop
        echo "label-agent: read-only is set in cmdline.txt but not active (overlayroot not working?)" >&2
    else
        echo "label-agent: switching read-only on and rebooting"
        raspi-config nonint enable_overlayfs && systemctl --no-block reboot
    fi
fi
exit 0
