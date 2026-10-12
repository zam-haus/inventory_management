# Logo and icons

`favicon-original.svg` is the design as exported from Adobe Illustrator, kept
unchanged for reference. The files the site serves are derived from it and live
in `inventory/static/inventory/favicon/`:

| File | What |
| --- | --- |
| `favicon.svg` | The original without Illustrator metadata, styles inlined. Renders identically. Also the logo at the top left of every frontend page. |
| `favicon.ico` | 16, 32 and 48 px, for browsers and tools that request `/favicon.ico`. |
| `apple-touch-icon.png` | 180 px with square corners: iOS rounds the icon itself and would fill transparent corners with black. |
| `icon-192.png`, `icon-512.png` | App icons for the [installed app](../installable-app.md). |
| `icon-maskable-512.png` | App icon with square corners and the motif shrunk into the safe zone, so Android launchers can crop it to any shape. |

On a dev system (`DEBUG` on), the site uses the variants in `dev/` instead: the
same files with the ZAM cyan (`#0eb8ef`) replaced by the ZAM magenta (`#e94391`,
rgb 233 67 145), so dev and production tabs and installed apps are easy to tell apart.

`templates/app_head.html` links them on every page (site, admin, printable
inventory). `/favicon.ico` and `/favicon.svg` are also served by Django, because
the resolver hosts (`i.zam.haus`, `id.zam.haus`) do not serve static files.

After a change to `favicon.svg`, regenerate everything else, including all dev
variants, from the repository root (needs `rsvg-convert` and Pillow):

```sh
docs/branding/generate-icons.sh
```
