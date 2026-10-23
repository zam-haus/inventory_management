#!/bin/sh
# Install the label print agent as a service. Runs once at boot (prepare-boot.sh adds it to cmdline.txt),
# or by hand: sudo sh /boot/label-agent/install.sh
# It never fails: a failing script would leave the Pi in the minimal boot target without login.
exec >>/var/log/label-agent-install.log 2>&1
echo "$(date): installing the label print agent"
boot=/boot
for candidate in /boot/firmware /boot; do
    if [ -d "$candidate/label-agent" ]; then boot=$candidate; break; fi
done
# First take this script out of the kernel command line, so the Pi boots normally whatever happens.
sed -i 's| systemd.run=[^ ]*label-agent/install.sh||; s| systemd.run_success_action=[^ ]*||; s| systemd.unit=kernel-command-line.target||' "$boot/cmdline.txt"
if mkdir -p /opt/label-agent \
        && cp "$boot/label-agent/update.sh" /opt/label-agent/update.sh \
        && sh /opt/label-agent/update.sh \
        && cp "$boot/label-agent/label-agent.service" /etc/systemd/system/label-agent.service \
        && systemctl enable label-agent.service; then
    echo "label-agent installed; it starts after the reboot"
else
    echo "label-agent: installing failed, see above; run again with: sudo sh $boot/label-agent/install.sh"
fi
exit 0
