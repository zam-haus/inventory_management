# Favicon

`favicon-original.svg` is the design as exported from Adobe Illustrator, kept
unchanged for reference. The files the site serves are derived from it and live
in `inventory/static/inventory/favicon/`:

| File | What |
| --- | --- |
| `favicon.svg` | The original without Illustrator metadata, styles inlined. Renders identically. |
| `favicon.ico` | 16, 32 and 48 px, for browsers and tools that request `/favicon.ico`. |
| `apple-touch-icon.png` | 180 px with square corners: iOS rounds the icon itself and would fill transparent corners with black. |

`templates/favicon.html` links them on every page (site, admin, printable
inventory). `/favicon.ico` and `/favicon.svg` are also served by Django, because
the resolver hosts (`i.zam.haus`, `id.zam.haus`) do not serve static files.

To regenerate after a design change (needs `rsvg-convert` and Pillow):

```sh
cd inventory/static/inventory/favicon
sed 's/ rx="96"//' favicon.svg > /tmp/favicon-square.svg
rsvg-convert -w 180 -h 180 /tmp/favicon-square.svg -o apple-touch-icon.png
rsvg-convert -w 256 -h 256 favicon.svg -o /tmp/favicon-256.png
python -c "from PIL import Image; Image.open('/tmp/favicon-256.png').save('favicon.ico', sizes=[(16, 16), (32, 32), (48, 48)])"
```
