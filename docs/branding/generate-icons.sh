#!/bin/sh
# Derive all served icons from inventory/static/inventory/favicon/favicon.svg,
# for production (ZAM cyan) and the dev system (dev/, ZAM magenta).
# Needs rsvg-convert and Python with Pillow. Run from the repository root.
set -eu

CYAN='#0eb8ef'
MAGENTA='#e94391'
DIR=inventory/static/inventory/favicon
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

sed -e "s/$CYAN/$MAGENTA/" \
    -e 's|<!-- Cleaned.*-->|<!-- Dev-system variant of ../favicon.svg: ZAM cyan replaced by ZAM magenta. -->|' \
    "$DIR/favicon.svg" > "$DIR/dev/favicon.svg"

for out in "$DIR" "$DIR/dev"; do
    # Square corners: iOS and Android round the icon themselves.
    sed 's/ rx="96"//' "$out/favicon.svg" > "$TMP/square.svg"
    # Maskable: the motif shrunk into the safe zone (circle of 80 % diameter),
    # so launchers may crop the square to any shape.
    sed -e 's/ rx="96"//' \
        -e 's|\(<rect width="512" height="512"[^>]*/>\)|\1<g transform="translate(256 256) scale(0.7) translate(-256 -256)">|' \
        -e 's|</svg>|</g></svg>|' "$out/favicon.svg" > "$TMP/maskable.svg"

    rsvg-convert -w 180 -h 180 "$TMP/square.svg" -o "$out/apple-touch-icon.png"
    rsvg-convert -w 192 -h 192 "$out/favicon.svg" -o "$out/icon-192.png"
    rsvg-convert -w 512 -h 512 "$out/favicon.svg" -o "$out/icon-512.png"
    rsvg-convert -w 512 -h 512 "$TMP/maskable.svg" -o "$out/icon-maskable-512.png"
    rsvg-convert -w 256 -h 256 "$out/favicon.svg" -o "$TMP/256.png"
    python3 -c "from PIL import Image; Image.open('$TMP/256.png').save('$out/favicon.ico', sizes=[(16, 16), (32, 32), (48, 48)])"
done
