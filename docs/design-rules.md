# Design rules: text, links and the ZAMid

Two rules for every page, list and dialog; buttons and their colours are in [Icons and action buttons](icons.md),
how locations are named in [Location purpose and photo](locations.md). The shared CSS is
`inventory/static/inventory/text.css`, loaded on every page (`templates/base.html`) and in the printable inventory.

## Text and links: blue means link

* **Blue is for links, and every text link is blue:** one colour, Bootstrap's link colour (`var(--bs-link-color)`,
  `#0d6efd`), also in map popups and on the standalone pages (resolver, printable inventory). Text that is not a link
  is never blue.
* **Icons are never blue,** also inside a link: they keep the text's colour (`a .type-icon` in `text.css`, the
  breadcrumbs in `breadcrumbs.css`). Buttons, menus and icon-only links colour their own icons.
* **Underlined:**
  * **names in lists** (result rows, the location and item trees, the levels-and-axes overview): on hover and focus only;
    blue and bold tell them apart;
  * **every other text link** (running text and markdown, the lines below a result row's name such as places,
    category and path, breadcrumbs, counts, back links, links in headings): always, thicker on hover. A link around a
    location's label underlines the title only, not the code chip after it (`locations.css`).
* **Bold** (600) marks what something *is*, never that it is a link:
  * the name of an entry in a list (`.result-title`, `.tree-name`, `.structure-node-title`);
  * the page itself, the last breadcrumb (`aria-current`): dark, bold, still underlined where it is a link;
  * labels of values (`dt`, eyebrows): grey `#59636e` and bold, their size per page;
  * headings are 650, numbers in count badges 700.
* **Grey links** only where a link is meant to stay in the background: the help link `{% help_link %}` (grey,
  underlined and blue on hover).
* **Chips, pills and filters** (location code chips, the contents chips of a location, the help's contents, the
  kind filters of the search) are controls: their own colours, never underlined.

| What | Colour | Underline | Weight |
|---|---|---|---|
| Name in a list | blue | on hover | 600 |
| Any other text link | blue | always | as the text |
| The page itself (breadcrumb) | text colour | if a link | 600 |
| Help link | grey | on hover | as the text |
| Chips, pills, buttons | their own | never | their own |
| Icons, also in links | text colour | – | – |
| Text that is no link | never blue | never | 600 only for names, labels, the page itself |

## The ZAMid

Location codes and ZAMids belong together on the label and on the screen, and are told apart the same way in both:

| | On the label | On the web |
|---|---|---|
| Location code | inverted: white on black, `font mono  bold  invert` | inverted: white monospace on a slate chip (`.loc-code`) |
| ZAMid | plain: black Roboto Mono 700, `font mono  bold` | plain: Roboto Mono 700 in the colour around it (`.zamid`) |

* **On the web** a ZAMid is its display form `K7R-4XD` (with the typed hyphen, so that it can be copied and found) in
  bold Roboto Mono, the font of the label, slightly spaced, never wrapped, without chip or icon, in the text's colour.
  Always through one helper: `{% zamid code %}` (`{% load locations %}`) or `label_ids.naming.html(code)` in Python.
* **A unique item is named** by one name, the item and its own name in one style ("Formatkreissäge Der
  Fingerverstümmler 3000", `UniqueItem.title`), then its ZAMid (`UniqueItem.code_html`; a unique item without one
  shows its number `#12`, grey). **A link to it holds the name only; the ZAMid follows outside the link**, as a
  location's code chip follows its name: never blue, never underlined, and it can be selected and copied. So: two
  styles, the name and the code. `UniqueItem.name_html` and `{% unique_item_label unique_item url=… %}`
  (`location_display.unique_item_html`) do this for result rows, place lines, breadcrumbs, headings and the print
  dialog; the map popups alike (`map.js`). The page's heading is the name and the ZAMid, not a link: the breadcrumb
  above it leads to the item.
* **In plain text** (page titles, messages, tooltips) it is named: “ZAMid K7R-4XD”, “Die ZAMid K7R-4XD ist bereits
  vergeben.” (`LABEL_ID_NAME`). The admin keeps “ID” and shows the canonical form (`K7R4XD`) where it is a URL.
* **On the label** the ZAMid labels print the name read from bottom to top in Raleway 800, the QR code and the code
  on two lines with a drawn bar between (`LABEL-ID-SPEC.md` §8); labels that show it in one line, e.g. the price tags,
  print `{{ label_id }}  font mono  bold`, beside the inverted location code.
* **The web font** is `inventory/static/inventory/fonts/roboto-mono-700.woff2` (7 KB): Roboto Mono at weight 700 from
  `label_printing/design/fonts`, cut down to ASCII by `docs/branding/generate-web-fonts.sh` (needs fonttools and
  brotli). Without it, pages fall back to the system's monospace.
