"""
ZAM ID algorithm (ZAM-ID-SPEC.md §5). Dependency-free; the only implementation
of the alphabet, check symbol and normalization. Do not re-implement elsewhere.
"""
import secrets

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXY"
VALUE = {c: i for i, c in enumerate(ALPHABET)}
N = 31
PAYLOAD_LEN = 5
ID_LEN = PAYLOAD_LEN + 1
RESERVED = {"000000"}
_LOOKALIKE = str.maketrans({"O": "0", "I": "1", "L": "1", "Z": "Y", "U": "V"})
_STRIP = str.maketrans("", "", "- _.")


class InvalidZamId(ValueError):
    """Raised for malformed input or a wrong check symbol."""


def check_symbol(payload: str) -> str:
    s = sum((i + 1) * VALUE[c] for i, c in enumerate(payload))
    return ALPHABET[(-s * 26) % N]


def is_valid(canonical: str) -> bool:
    return (len(canonical) == ID_LEN
            and all(c in VALUE for c in canonical)
            and sum((i + 1) * VALUE[c] for i, c in enumerate(canonical)) % N == 0)


def normalize(raw: str) -> str:
    """Return the canonical ID or raise InvalidZamId."""
    s = raw.strip().translate(_STRIP).upper().translate(_LOOKALIKE)
    if len(s) != ID_LEN or any(c not in VALUE for c in s):
        raise InvalidZamId("malformed")
    if not is_valid(s):
        raise InvalidZamId("checksum")
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
