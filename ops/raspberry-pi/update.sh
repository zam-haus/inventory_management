#!/bin/sh
# Copy the agent's code from the boot partition (Raspberry Pi OS: /boot, from bookworm on /boot/firmware).
for boot in /boot/firmware /boot; do
    if [ -d "$boot/label-agent/label_printing" ]; then
        rm -rf /opt/label-agent/label_printing.new
        cp -r "$boot/label-agent/label_printing" /opt/label-agent/label_printing.new
        find /opt/label-agent/label_printing.new -name '._*' -delete  # macOS leaves these on FAT
        rm -rf /opt/label-agent/label_printing
        mv /opt/label-agent/label_printing.new /opt/label-agent/label_printing
        exit 0
    fi
done
echo "label-agent: no label-agent/ on the boot partition, keeping the installed code" >&2
