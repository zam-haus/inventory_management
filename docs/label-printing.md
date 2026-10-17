# Label printing

Print jobs are passed to the printer via MQTT. A simple print server, listening to a (currently) hard-coded topic on mqtt.zam.haus and passing them onto a (currently) hard-coded printer is implemented by `print_server.py`. A more flexible (and complex) solution is planned.

Label ID labels for Brother P-touch printers are rendered as PNGs instead; see
[Label IDs](label-ids.md#labels).
