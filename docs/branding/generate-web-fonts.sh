#!/bin/sh
# The web font of the ZAMid (docs/design-rules.md): Roboto Mono 700, the font the labels print it in
# (label_printing/design/fonts), cut down to the characters of IDs and codes, as woff2.
# Needs Python with fonttools and brotli. Run from the repository root.
set -eu

SRC='label_printing/design/fonts/RobotoMono%5Bwght%5D.ttf'
DIR=inventory/static/inventory/fonts
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$DIR"
python3 -m fontTools.varLib.instancer "$SRC" wght=700 -o "$TMP/bold.ttf"
python3 -m fontTools.subset "$TMP/bold.ttf" \
    --unicodes='U+0020-007E,U+00B7,U+2013,U+2026' \
    --layout-features='' --no-hinting --desubroutinize \
    --flavor=woff2 --output-file="$DIR/roboto-mono-700.woff2"
cp label_printing/design/fonts/OFL-RobotoMono.txt "$DIR/"
