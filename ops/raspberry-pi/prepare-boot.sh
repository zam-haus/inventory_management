#!/bin/sh
# Prepare the boot partition of a Raspberry Pi OS SD card (mounted on this computer) to run the label
# print agent: copies the agent and the service there and lets the Pi install it on its next boot.
#
#   ops/raspberry-pi/prepare-boot.sh /Volumes/boot [SERVER TOKEN ...]
#
# Each SERVER (e.g. https://inventar.zam.haus) with the agent's TOKEN from that inventory's admin
# (Label printing → Print agents → add) goes into label-agent/config.json; without them an existing
# config.json is kept. Running it again updates the code; the agent picks it up when it restarts
# (sudo systemctl restart label-agent, or reboot).
set -e
boot=${1:?usage: prepare-boot.sh BOOT_PARTITION [SERVER TOKEN ...]}
shift
[ $(($# % 2)) -eq 0 ] || { echo "give a TOKEN after each SERVER (from the inventory's admin)" >&2; exit 1; }
[ -f "$boot/cmdline.txt" ] || { echo "$boot has no cmdline.txt: not a Raspberry Pi boot partition" >&2; exit 1; }
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
dest="$boot/label-agent"
mkdir -p "$dest/label_printing/devices"
cp "$repo/label_printing/__init__.py" "$repo/label_printing/agent.py" "$dest/label_printing/"
cp "$repo"/label_printing/devices/*.py "$dest/label_printing/devices/"
cp "$here/install.sh" "$here/update.sh" "$here/label-agent.service" "$dest/"
if [ $# -gt 0 ]; then
    servers=$(printf '{"url": "%s", "token": "%s"}, ' "$@"); servers=${servers%, }
    tr '\n' '\r' < "$here/config.json" | sed "s|\"servers\": \[[^]]*\]|\"servers\": [$servers]|" | tr '\r' '\n' \
        > "$dest/config.json"
elif [ ! -f "$dest/config.json" ]; then
    cp "$here/config.json" "$dest/config.json"
fi

# Install on the next boot, the way Raspberry Pi Imager runs its firstrun.sh. The Pi mounts this
# partition on /boot, from Raspberry Pi OS bookworm (images of 2023-10 and later) on /boot/firmware.
image_date=$(sed -n 's/.*reference \([0-9-]*\).*/\1/p' "$boot/issue.txt" 2>/dev/null | tr -d -)
mount=/boot; [ "${image_date:-0}" -ge 20231010 ] && mount=/boot/firmware
cmdline=$(cat "$boot/cmdline.txt")
case "$cmdline" in
    *label-agent/install.sh*) ;;
    *) printf '%s systemd.run=%s/label-agent/install.sh systemd.run_success_action=reboot systemd.unit=kernel-command-line.target\n' \
           "$(printf '%s' "$cmdline" | tr -d '\n')" "$mount" > "$boot/cmdline.txt" ;;
esac
# macOS keeps extended attributes on FAT as ._ files; the Pi does not need them.
find "$dest" -name '._*' -delete
echo "Prepared $boot: agent in label-agent/, servers: $(grep -o '"url": "[^"]*"' "$dest/config.json" | tr '\n' ' ')"
