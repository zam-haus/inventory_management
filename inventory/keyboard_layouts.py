"""Undo keyboard layout mismatches of barcode scanners in keyboard mode.

A scanner sends physical keys for the characters it decodes, using its own
layout; the host interprets those keys with its layout. A US scanner on a
German host thus types "httpsÖ--inv.yam.haus-" for "https://inv.zam.haus/".
"""

from itertools import permutations


def _layout(*rows):
    # One token per physical key: its unshifted and shifted character; "\0"
    # marks a level without a character. Rows run from the number row down to
    # the bottom row; the last key of the home row is the ANSI backslash or ISO
    # "#" key, the first key of the bottom row the ISO key next to left Shift.
    return [row.split(" ") for row in rows]


LAYOUTS = {
    "us": _layout(
        "`~ 1! 2@ 3# 4$ 5% 6^ 7& 8* 9( 0) -_ =+",
        "qQ wW eE rR tT yY uU iI oO pP [{ ]}",
        "aA sS dD fF gG hH jJ kK lL ;: '\" \\|",
        "\\| zZ xX cC vV bB nN mM ,< .> /?",
    ),
    "de": _layout(
        "^° 1! 2\" 3§ 4$ 5% 6& 7/ 8( 9) 0= ß? ´`",
        "qQ wW eE rR tT zZ uU iI oO pP üÜ +*",
        "aA sS dD fF gG hH jJ kK lL öÖ äÄ #'",
        "<> yY xX cC vV bB nN mM ,; .: -_",
    ),
    "ch": _layout(
        "§° 1+ 2\" 3* 4ç 5% 6& 7/ 8( 9) 0= '? ^`",
        "qQ wW eE rR tT zZ uU iI oO pP üè ¨!",
        "aA sS dD fF gG hH jJ kK lL öé äà $£",
        "<> yY xX cC vV bB nN mM ,; .: -_",
    ),
    "uk": _layout(
        "`¬ 1! 2\" 3£ 4$ 5% 6^ 7& 8* 9( 0) -_ =+",
        "qQ wW eE rR tT yY uU iI oO pP [{ ]}",
        "aA sS dD fF gG hH jJ kK lL ;: '@ #~",
        "\\| zZ xX cC vV bB nN mM ,< .> /?",
    ),
    "fr": _layout(
        "²\0 &1 é2 \"3 '4 (5 -6 è7 _8 ç9 à0 )° =+",
        "aA zZ eE rR tT yY uU iI oO pP ^¨ $£",
        "qQ sS dD fF gG hH jJ kK lL mM ù% *µ",
        "<> wW xX cC vV bB nN ,? ;. :/ !§",
    ),
}

# Where each character is typed: (row, key, shift level). The first key wins
# for characters available twice, such as the US backslash.
_POSITIONS = {
    name: {
        char: (row_index, key_index, level)
        for row_index, row in reversed(list(enumerate(rows)))
        for key_index, key in reversed(list(enumerate(row)))
        for level, char in enumerate(key)
        if char != "\0"
    }
    for name, rows in LAYOUTS.items()
}


def retype(text, sender, receiver):
    """Return text as a `receiver` host reads keys sent for it by a `sender`.

    Characters outside the layouts, like spaces, use the same key everywhere
    and pass through. Returns None if a character has no counterpart.
    """
    positions, rows = _POSITIONS[sender], LAYOUTS[receiver]
    result = []
    for char in text:
        if char not in positions:
            result.append(char)
            continue
        row, key, level = positions[char]
        typed = rows[row][key][level]
        if typed == "\0":
            return None
        result.append(typed)
    return "".join(result)


def layout_corrections(value, prefix):
    """Yield readings of a scanned value that starts with a garbled `prefix`."""
    seen = set()
    for scanner, host in permutations(LAYOUTS, 2):
        garbled_prefix = retype(prefix, scanner, host)
        if not garbled_prefix or garbled_prefix == prefix or not value.startswith(garbled_prefix):
            continue
        corrected = retype(value, host, scanner)
        if corrected and corrected.startswith(prefix) and corrected not in seen:
            seen.add(corrected)
            yield corrected
