"""
A minimal SNMP v1 GET (UDP), enough to read one value from a printer; no dependencies.

Brother network printers do not answer status requests on their print port, but report the same
32-byte status record as over USB under OID 1.3.6.1.4.1.2435.3.3.9.1.6.1.0.
"""
import itertools
import socket

DEFAULT_PORT = 161
_request_ids = itertools.count(1)


def _length(n):
    if n < 0x80:
        return bytes([n])
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _tlv(tag, value):
    return bytes([tag]) + _length(len(value)) + value


def _integer(value):
    return _tlv(0x02, value.to_bytes(max(1, (value.bit_length() + 8) // 8), "big", signed=True))


def _oid(oid):
    parts = [int(part) for part in oid.split(".")]
    encoded = bytes([parts[0] * 40 + parts[1]])
    for part in parts[2:]:
        chunk = [part & 0x7F]
        part >>= 7
        while part:
            chunk.insert(0, 0x80 | (part & 0x7F))
            part >>= 7
        encoded += bytes(chunk)
    return encoded


def get_request(oid, community="public", request_id=1):
    varbind = _tlv(0x30, _tlv(0x06, _oid(oid)) + _tlv(0x05, b""))
    pdu = _tlv(0xA0, _integer(request_id) + _integer(0) + _integer(0) + _tlv(0x30, varbind))
    return _tlv(0x30, _integer(0) + _tlv(0x04, community.encode()) + pdu)


def _read(data, i):
    tag, length = data[i], data[i + 1]
    i += 2
    if length & 0x80:
        size = length & 0x7F
        length = int.from_bytes(data[i:i + size], "big")
        i += size
    return tag, data[i:i + length], i + length


def _values(data):
    """The primitive values of a BER message, in order (constructed types are walked into)."""
    found, i = [], 0
    while i < len(data):
        tag, value, i = _read(data, i)
        if tag & 0x20:  # constructed: SEQUENCE, GetResponse …
            found.extend(_values(value))
        else:
            found.append((tag, value))
    return found


def get(host, oid, community="public", port=DEFAULT_PORT, timeout=2.0):
    """The value of `oid` as bytes, or None if there is no answer (or an error)."""
    request_id = next(_request_ids) % 0x7FFFFFFF
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.sendto(get_request(oid, community, request_id), (host, port))
            data, _address = sock.recvfrom(4096)
        except OSError:  # timeout (socket.timeout before Python 3.10), unreachable
            return None
    try:
        values = _values(data)
    except IndexError:
        return None
    # version, community, request ID, error status, error index, OID, value
    if len(values) < 7 or values[3][1] != b"\x00" or values[-1][0] in (0x05, 0x80, 0x81, 0x82):
        return None
    return values[-1][1]


def response(oid, value, community="public", request_id=1):
    """A GetResponse with an octet string (for fake printers in tests)."""
    varbind = _tlv(0x30, _tlv(0x06, _oid(oid)) + _tlv(0x04, value))
    pdu = _tlv(0xA2, _integer(request_id) + _integer(0) + _integer(0) + _tlv(0x30, varbind))
    return _tlv(0x30, _integer(0) + _tlv(0x04, community.encode()) + pdu)


def request_id_of(message):
    """The request ID of a GetRequest (for fake printers)."""
    return int.from_bytes(_values(message)[2][1], "big", signed=True)
