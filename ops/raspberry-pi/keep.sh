#!/bin/sh
# Runs as root when the agent changed Bluetooth pairings (label-agent-keep.path): saves BlueZ's pairings
# (/var/lib/bluetooth, which the agent may not read) on the boot partition, so they survive a reboot of a Pi
# whose system is read-only; update.sh puts them back on the next boot. Written only on a change, as one file.
sleep 2  # BlueZ writes the pairing's key once pairing is done
for boot in /boot/firmware /boot; do
    if [ -d "$boot/label-agent" ]; then
        tar -czf "$boot/label-agent/bluetooth.tgz.new" -C /var/lib bluetooth \
            && mv "$boot/label-agent/bluetooth.tgz.new" "$boot/label-agent/bluetooth.tgz" \
            && echo "label-agent: Bluetooth pairings saved on $boot"
        sync
        break
    fi
done
rm -f /run/label-agent/keep-bluetooth
exit 0
