#!/bin/sh
# Update a running Pi over SSH: copies the agent's code and service files from this repository into
# label-agent/ on its boot partition (config.json with its tokens stays as it is) and restarts the agent,
# which copies them to /opt (update.sh). Needs sudo without password on the Pi (Raspberry Pi OS default).
#
#   ops/raspberry-pi/push.sh pi@pi-lager.local
set -e
host=${1:?usage: push.sh USER@HOST}
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
cd "$repo"
# COPYFILE_DISABLE: no macOS ._ files in the archive
COPYFILE_DISABLE=1 tar --no-xattrs -cf - label_printing/__init__.py label_printing/agent.py label_printing/station.py \
        label_printing/touch.py label_printing/devices/*.py \
        -C "$here" install.sh update.sh keep.sh label-agent.service label-agent-keep.path label-agent-keep.service \
    | ssh "$host" 'set -e
        boot=/boot/firmware; [ -d "$boot/label-agent" ] || boot=/boot
        [ -d "$boot/label-agent" ] || { echo "no label-agent/ on $boot: prepare the card first (prepare-boot.sh)" >&2; exit 1; }
        sudo tar -x -m --no-same-owner --no-same-permissions -C "$boot/label-agent"
        # on the card before anything restarts: a reboot that hangs (read-only switched off and on by update.sh)
        # would otherwise leave the files empty
        sync
        if find "$boot/label-agent" -type f -size 0 ! -name config.json ! -name '*.tgz' | grep -q .; then
            echo "empty files in $boot/label-agent after copying: card or power trouble?" >&2; exit 1
        fi
        # the service files: update.sh puts them in place (read-only: in a start with the overlay off)
        sudo systemctl restart label-agent
        sleep 3
        systemctl --no-pager --lines=15 status label-agent'
