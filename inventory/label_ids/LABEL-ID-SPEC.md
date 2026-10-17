# Label ID Scheme — Implementation Spec

> Written for ZAM (`zam.haus`), whose hostnames serve as examples and defaults. Code,
> database and settings say "label ID"; users see the name in `LABEL_ID_NAME`
> (ZAM: `ZAMid`). Another organization changes that setting and the host settings.

Target: embed into the **existing Django project** behind `inv.zam.haus`.
Audience: Claude Code (implementer). Read the whole document before changing code.
Before you start, inspect the project and **ask** about anything listed in §12 ("Open decisions") that the codebase doesn't answer.

---

## 1. Purpose

Every uniquely tracked item at ZAM (tools, machines, devices, cables, small parts…) gets a short, permanent ID printed as a QR code plus human-readable text on a Brother P-touch label.

Requirements:

- Human-readable and typeable without confusion (no `I l 1 | O 0 o` ambiguities, robust to QWERTZ/QWERTY Y/Z swaps).
- Typos are **detected**, not resolved to a wrong item.
- QR code is a full HTTPS URL and fits in the **smallest standard QR code (Version 1, 21×21 modules)** so labels can be ~1 cm.
- IDs are opaque and permanent: they never encode category, location or owner, are never reused, and the resolver URL must outlive the inventory software.

---

## 2. ID format

### 2.1 Alphabet (31 symbols)

```
0123456789ABCDEFGHJKMNPRSTUVWXY
```

Value of a symbol = its index in this string (`0`→0 … `9`→9, `A`→10 … `Y`→30).
Excluded letters: `I L O Q Z` (confusable with `1 1 0 0 Y`, the last one due to QWERTZ/QWERTY).

### 2.2 Structure

| Part | Length | Content |
|---|---|---|
| Payload | 5 | random symbols from the alphabet |
| Check | 1 | check symbol, see §3 |

- **Canonical form**: 6 uppercase symbols, no separator — `K7R4XD`. This is what is stored in the database and put in URLs/QR codes.
- **Display form**: `K7R-4XD` (hyphen after the 3rd symbol). Use for UI, lists, emails.
- **Label form**: two lines `K7R` / `-` / `4XD` (see §8).
- ID space: 31⁵ = 28,629,151 IDs.
- Payload `00000` (canonical `000000`) is **reserved for tests/demos** and must never be issued.

> Note: `K7R4XR` is **not valid** (its check symbol is `D`); it serves as the typo example. Earlier drafts used `K7Q4XD`, which is invalid since `Q` was removed. Use `K7R4XD` as the example.

---

## 3. Check symbol

Weighted sum modulo 31 (31 is prime). Positions are numbered 1…6, weight = position.

A canonical ID `c1 c2 c3 c4 c5 c6` is valid iff

```
(1·v(c1) + 2·v(c2) + 3·v(c3) + 4·v(c4) + 5·v(c5) + 6·v(c6)) mod 31 == 0
```

Computing the check symbol for payload `p1…p5`:

```
s  = Σ i·v(pi)  for i = 1..5
c6 = ALPHABET[(-s · 26) mod 31]        # 26 is the inverse of 6 mod 31
```

Guaranteed properties (must be covered by tests, §11):

- detects **every** single-symbol substitution,
- detects **every** swap of two different symbols at **any** two positions (not only adjacent).

### 3.1 Test vectors

| Payload | Canonical ID | Display |
|---|---|---|
| `00000` | `000000` | `000-000` (reserved) |
| `00001` | `00001T` | `000-01T` |
| `10000` | `100005` | `100-005` |
| `12345` | `12345V` | `123-45V` |
| `ABCDE` | `ABCDEM` | `ABC-DEM` |
| `K7R4X` | `K7R4XD` | `K7R-4XD` |
| `5S8B2` | `5S8B24` | `5S8-B24` |
| `YYYYY` | `YYYYYJ` | `YYY-YYJ` |

---

## 4. Input normalization

Every place that accepts an ID from a human or a URL (resolver path, search box, form fields, API) must normalize first:

1. Strip leading/trailing whitespace.
2. Remove all `-`, spaces, `_` and `.` inside.
3. Uppercase.
4. Map lookalikes: `O→0`, `Q→0`, `I→1`, `L→1`, `Z→Y`.
5. Result must be exactly 6 symbols from the alphabet, else **malformed**.
6. Then check the check symbol, else **checksum error**.

Normalization is lenient; storage is strict (canonical only).

---

## 5. Reference implementation

Put this in a small, dependency-free module (e.g. `label_ids/core.py`) and use it everywhere. Do not re-implement the algorithm elsewhere.

```python
import secrets

ALPHABET = "0123456789ABCDEFGHJKMNPRSTUVWXY"
VALUE = {c: i for i, c in enumerate(ALPHABET)}
N = 31
PAYLOAD_LEN = 5
ID_LEN = PAYLOAD_LEN + 1
RESERVED = {"000000"}
_LOOKALIKE = str.maketrans({"O": "0", "Q": "0", "I": "1", "L": "1", "Z": "Y"})
_STRIP = str.maketrans("", "", "- _.")


class InvalidLabelId(ValueError):
    """Raised for malformed input or a wrong check symbol."""


def check_symbol(payload: str) -> str:
    s = sum((i + 1) * VALUE[c] for i, c in enumerate(payload))
    return ALPHABET[(-s * 26) % N]


def is_valid(canonical: str) -> bool:
    return (len(canonical) == ID_LEN
            and all(c in VALUE for c in canonical)
            and sum((i + 1) * VALUE[c] for i, c in enumerate(canonical)) % N == 0)


def normalize(raw: str) -> str:
    """Return the canonical ID or raise InvalidLabelId."""
    s = raw.strip().translate(_STRIP).upper().translate(_LOOKALIKE)
    if len(s) != ID_LEN or any(c not in VALUE for c in s):
        raise InvalidLabelId("malformed")
    if not is_valid(s):
        raise InvalidLabelId("checksum")
    return s


def generate() -> str:
    """Random new ID (caller must check uniqueness against the DB)."""
    while True:
        p = "".join(secrets.choice(ALPHABET) for _ in range(PAYLOAD_LEN))
        cid = p + check_symbol(p)
        if cid not in RESERVED:
            return cid


def display(canonical: str) -> str:
    return f"{canonical[:3]}-{canonical[3:]}"


def suggestions(raw: str) -> list[str]:
    """
    For a 6-symbol input with a checksum error: all valid IDs that differ by one
    substitution or one swap of two positions. Caller filters to IDs that exist.
    """
    s = raw.strip().translate(_STRIP).upper().translate(_LOOKALIKE)
    if len(s) != ID_LEN or any(c not in VALUE for c in s):
        return []
    out = set()
    for i in range(ID_LEN):
        for c in ALPHABET:
            t = s[:i] + c + s[i + 1:]
            if t != s and is_valid(t):
                out.add(t)
    for i in range(ID_LEN):
        for j in range(i + 1, ID_LEN):
            l = list(s); l[i], l[j] = l[j], l[i]
            t = "".join(l)
            if t != s and is_valid(t):
                out.add(t)
    return sorted(out - RESERVED)
```

---

## 6. Data model (Django)

Adapt names to the project's conventions. The ID lives in its **own table** so that IDs can exist before they are attached to an item (pre-printed label rolls) and stay reserved after an item is retired.

### 6.1 Custom field

`LabelIdField(models.CharField)`:

- `max_length=6`, uppercase canonical value only.
- `to_python` / `get_prep_value` / `formfield` call `normalize()`; validation errors map `InvalidLabelId("malformed")` and `("checksum")` to distinct, translatable `ValidationError` messages (German UI texts, e.g. „Ungültige ID“ / „Prüfzeichen stimmt nicht – Tippfehler?“).
- Form widget shows/accepts the display form `K7R-4XD`.

### 6.2 Model `LabelId`

| Field | Type | Notes |
|---|---|---|
| `code` | `LabelIdField`, **primary key** | canonical, immutable |
| `status` | choices: `reserved`, `assigned`, `retired` | see lifecycle |
| `item` | FK/OneToOne to the project's item model, nullable, `on_delete=PROTECT` | set when assigned; see §12 |
| `batch` | CharField, blank | label batch / print run name |
| `created_at` | DateTime auto | |
| `printed_at` | DateTime null | set by the label command |
| `assigned_at` | DateTime null | |
| `assigned_by` | FK user null | |
| `retired_at` | DateTime null | |
| `note` | TextField blank | |

Constraints:

- `item` unique among non-retired rows (one active ID per item). Decide with the user whether an item may have several active IDs (e.g. replaced label) — default: **no**, a replaced label retires the old ID.
- A `CheckConstraint` or model `clean()` ensuring `status == "assigned"` ⇔ `item IS NOT NULL`.

### 6.3 Lifecycle

```
generate ──► reserved ──(claim / assign)──► assigned ──(retire)──► retired
                 └──────────────(void unused label)───────────────► retired
```

- **Never delete** rows and **never reuse** a code. Retired codes resolve to an explanatory page.
- Re-assigning an `assigned` code to another item is not allowed; retire and issue a new code instead.

### 6.4 Generation

- `generate()` + `INSERT`; on `IntegrityError` (collision) retry. Wrap batch generation in a transaction.
- Collision probability is negligible at ZAM scale but must still be handled.

---

## 7. URLs and resolver

### 7.1 Hostnames

| Host | Role |
|---|---|
| `i.zam.haus` | **Permanent QR resolver.** Only path `/<id>`. Never changes, independent of the inventory software. |
| `id.zam.haus` | Human entry point: lookup form at `/`, same resolver at `/<id>`. |
| `inv.zam.haus` | The Django inventory app itself. |

All three hostnames point at this Django project (add to `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, TLS certs). Route by host — either a small middleware that dispatches `i.`/`id.` requests to a dedicated URLconf (`request.urlconf = "label_id.urls_resolver"`) or `django-hosts` if the project already uses it. Do not add a new dependency without reason.

### 7.2 QR content

```
HTTPS://I.ZAM.HAUS/<CANONICAL>
e.g. HTTPS://I.ZAM.HAUS/K7R4XD
```

Entirely uppercase on purpose (QR alphanumeric mode). Scheme and host are case-insensitive; **the path must be matched case-insensitively** by the resolver.

The base comes from the setting `LABEL_ID_BASE_URL` (default `https://i.zam.haus/`, uppercased for the QR code). Local test setups use `http://i.localhost:8000/`; such longer bases need a larger QR version (2), and labels then use smaller modules so the code still fits the tape.

### 7.3 Resolver behaviour (`GET|HEAD /<anything>` on `i.` and `id.`)

| Input after `normalize()` | Response |
|---|---|
| valid, `assigned` | **302** → item detail URL on `inv.zam.haus` (absolute URL, built from the item model's `get_absolute_url()`) |
| valid, `reserved` | 302 → claim page on `inv.zam.haus` (`/id/<code>/claim/`), login required there |
| valid, `retired` | 410 page: "this label is no longer in use", link to the item if any |
| valid, unknown (never generated) | 404 page: "unknown ID", lookup form |
| checksum error | 404 page "typo?" listing `suggestions()` that exist in the DB, plus lookup form |
| malformed | 404 page with lookup form |
| `/` on `id.zam.haus` | lookup form (GET param `q`, normalizes and redirects to `/<code>`) |
| `/` on `i.zam.haus` | 302 → `https://id.zam.haus/` |

Exception, to record accesses (§7.5): when the path is exactly the canonical code, as printed in the QR code, and the ID exists, the response is first a 302 to `/id/<code>?via=<method>` on the inventory host, which records the access and then answers as in the table. The lookup form likewise redirects to that inventory URL.

Rules:

- Use **302**, never 301 (targets may change; 301 is cached forever by browsers).
- Any input that normalizes to a valid ID (`k7r-4xd`, `K7R 4XD`, lookalikes) resolves directly; no extra canonicalizing redirect hop is needed. Only label scans and lookup form entries take the extra hop of §7.5.
- Resolver pages are public and contain no personal data. Item detail pages keep whatever auth the project already has.
- Add light rate limiting on the lookup/resolver (IDs are random and not secret, but enumeration should be unattractive).
- Resolver must not depend on heavy app code: keep it in its own app/views so it can be split out later.

### 7.4 Inventory-side URLs (`inv.zam.haus`)

| Path | Purpose |
|---|---|
| `/id/<code>/` | ID detail (status, history, item link) — staff |
| `/id/<code>/claim/` | Attach a `reserved` ID to an existing item or create a new item with it |
| `/id/<code>/qr.svg`, `/id/<code>/qr.png` | QR code image (§8.1) |
| search | global search box accepts IDs in any form → `normalize()` → redirect via `/id/<code>?via=<method>` (a web form access, §7.5) to the item |

### 7.5 Last accesses

The last accesses of each ID are kept, 5 by default (setting/environment variable `LABEL_ID_ACCESS_KEEP`) (`LabelIdAccess`: time, user, method, and whether the request came from the local network per `LOCAL_NETWORK_SOURCES`, independent of the user's local group) and shown on `/id/<code>/info/` and the label ID admin page.

| Method | Counted when |
|---|---|
| label scan | the QR code's URL is opened: canonical code on a resolver host (`HTTPS://I.ZAM.HAUS/K7R4XD`), including the inventory's own camera scanner |
| web form | an ID is entered in the lookup form (`id.zam.haus`, `/id/`) or the inventory search box |

- Not counted: links clicked inside the inventory (plain `/id/<code>`), typed resolver URLs in other forms, `HEAD` requests.
- The resolver hosts cannot see the inventory login (its cookie is bound to the inventory domain, and a cookie cannot span `zam.haus` and `betreiberverein.de`). So they redirect to `/id/<code>?via=<method>` on the inventory host (`LABEL_ID_INVENTORY_BASE`), which records the access with the logged-in user (none if not logged in) and resolves.
- `<method>` is `label_scan` or `webform` and not protected: such URLs only exist between these redirects, and a QR code cannot be told apart from a pasted link anyway. Every answer to such a URL is a redirect: to the target, the claim page, or, for retired and deleted IDs, to the plain `/id/<code>`, so reloading the page shown is no further access.
- The user is **personal data**: shown only with the permission `inventory.view_labelid_access_user` (granted to no group by default). Older entries are deleted when a new one is recorded; deleting a user keeps the entry without user.

---

## 8. QR code and labels

### 8.1 QR generation

Use `segno`:

```python
qr = segno.make(f"HTTPS://I.ZAM.HAUS/{code}", error="l", micro=False, boost_error=False)
assert qr.version == 1 and qr.mode == "alphanumeric"
```

- Content is exactly 25 characters → Version 1, ECC level L. Never use lowercase (forces byte mode → bigger code).
- Do not use Micro QR / rMQR (not read by stock phone cameras, URL does not fit M4).
- For on-screen/print images render with `border=4` (quiet zone) and integer module scaling.

### 8.2 Labels

A separate, already-written script `idlabel.py` renders pixel-exact 1-bit PNGs for Brother PT-E550W (180 dpi) and PT-P900 series (360 dpi). Integrate it as-is (e.g. `label_ids/labels.py`, plus its `fonts/` and `zam-bildmarke.svg`), don't redesign it. Summary of what it does, for reference:

- Layout: `ZAM` vertical (bottom-to-top) | QR | `K7R` / `-` / `4XD`; first text line's cap tops on the QR's first pixel row, second line's lowest ink on the QR's last row, hyphen centred between.
- Logo: Raleway "ZAM" text on E550W 9/12/18 mm and P900 9 mm; official ZAM Bildmarke (SVG from the ZAM design system) elsewhere.
- ID font: Roboto Mono 700, rendered without anti-aliasing.
- Dots per QR module per tape: E550W 9/12/18/24 mm → 2/3/4/5; P900 9/12/18/24/36 mm → 4/6/9/12/18. Quiet zone 4 modules left/right.
- Print as raster in **standard** resolution (no "high resolution", no P-touch Editor rescaling), e.g. via the `ptouch` Python library; use half-cut chain printing for batches.

Requested integration:

- Management command `label_id_labels --batch NAME --printer {E550W,P900} --tape {9,12,18,24,36} [--print HOST]` → renders PNGs for all `reserved` codes of the batch (and optionally prints), sets `printed_at`.
- Admin/staff action "print label" for a single ID.

---

## 9. Management commands

| Command | Behaviour |
|---|---|
| `label_id_generate --count N --batch NAME` | create N new `reserved` IDs in one transaction; print them in display form |
| `label_id_labels …` | see §8.2 |
| `label_id_check <input>…` | print normalized form, validity, status, suggestions |
| `label_id_retire <code> [--note …]` | retire an ID |

---

## 10. Admin / UI

- `LabelId` admin: list display (display form, status, item, batch, dates), filters by status/batch, search accepts any input form (normalize first), actions: retire, print label.
- Item admin/detail: show the active ID (display form) and a QR thumbnail; "assign ID" via input field (scan or type) using `LabelIdField` validation.
- All user-facing strings translatable, German first.

---

## 11. Tests (required)

Unit tests for `core.py`:

- Test vectors from §3.1 (`check_symbol`, `is_valid`, `display`).
- `normalize`: `"k7r-4xd"`, `" K7R 4XD "`, `"K7R_4XD"` → `K7R4XD`; lookalike mapping for each of `O Q I L Z`; malformed inputs (length 5/7, `!`, empty) raise `malformed`; `K7R4XR` raises `checksum`.
- Property tests (Hypothesis if available, else seeded loop ≥10 000): every generated ID is valid; every single substitution of a valid ID is invalid; every swap of two different symbols at any two positions is invalid.
- `generate` never returns a reserved ID; alphabet never contains `I L O Q Z`.
- `suggestions("K7R4XR")` contains `K7R4XD`.

Integration tests:

- Resolver: each row of the table in §7.3 (status codes, `Location` headers, 302 not 301), case-insensitive paths, hyphenated paths, `HEAD` support, host routing for `i.`, `id.`, `inv.`.
- Model constraints and lifecycle transitions (no reassign, no delete, retire).
- QR: generated payload is version 1 / alphanumeric for random IDs.

---

## 12. Open decisions — ask the user before implementing

1. Which existing model(s) get IDs (single item model, several, or generic relation)?
2. One active ID per item, or several (e.g. multiple labels on a machine)?
3. Item detail URL pattern and auth on `inv.zam.haus`; may anonymous users see anything after scanning?
4. Host routing: existing setup (nginx, `django-hosts`, middleware)? Is TLS for `i.` and `id.` already in place?
5. Should existing inventory numbers be migrated/linked (e.g. store old number in `note` or an `legacy_id` field)?
6. Where labels are printed from (server with network access to the printers vs. a local workstation).

---

## 13. Out of scope

- Changing the alphabet, length, check algorithm or URL prefix — these are fixed because labels get printed with them.
- Redesigning the label layout (§8.2).
- Encoding any meaning (type, location, owner) into IDs.
