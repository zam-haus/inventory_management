"""Connections to printers: raw TCP (port 9100), USB printer devices (Linux usblp, /dev/usb/lp0) and
Bluetooth printers over RFCOMM (serial port profile)."""
import os
import re
import select
import socket
import time
from urllib.parse import urlsplit

DEFAULT_PORT = 9100


class DeviceError(OSError):
    """The printer could not be reached or the connection broke."""


class Device:
    """A bidirectional byte stream to a printer; use as a context manager."""

    def open(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def write(self, data: bytes):
        raise NotImplementedError

    def read(self, size: int, timeout: float) -> bytes:
        """Up to `size` bytes, as soon as some arrive; b"" if none came within `timeout` seconds."""
        raise NotImplementedError

    def read_exactly(self, size: int, timeout: float) -> bytes:
        """`size` bytes, or fewer if the time ran out."""
        deadline = time.monotonic() + timeout
        data = b""
        while len(data) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            chunk = self.read(size - len(data), remaining)
            if not chunk:
                break
            data += chunk
        return data

    def read_until(self, done, timeout: float) -> bytes:
        """Read until done(data) is true or the time runs out."""
        deadline = time.monotonic() + timeout
        data = b""
        while not done(data):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            chunk = self.read(4096, remaining)
            if not chunk:
                break
            data += chunk
        return data

    def drain(self, timeout: float = 0.05) -> bytes:
        """Whatever the printer sent unasked (e.g. status notifications), so the next reply is read cleanly."""
        return self.read_until(lambda data: False, timeout)

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()


class SocketDevice(Device):
    """A printer behind a socket; open() connects it."""
    sock = None

    def connect(self):
        raise NotImplementedError

    def open(self):
        try:
            self.sock = self.connect()
        except OSError as error:
            raise DeviceError(f"{self}: {error}") from error

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def write(self, data):
        try:
            self.sock.settimeout(30)
            self.sock.sendall(data)
        except OSError as error:
            raise DeviceError(f"{self}: {error}") from error

    def read(self, size, timeout):
        self.sock.settimeout(max(timeout, 0.001))
        try:
            return self.sock.recv(size)
        except socket.timeout:  # TimeoutError since Python 3.10, a separate OSError before
            return b""
        except OSError as error:
            raise DeviceError(f"{self}: {error}") from error


class TcpDevice(SocketDevice):
    """A network printer. Some answer status requests only over SNMP (snmp_port), not on the print port."""

    def __init__(self, host, port=DEFAULT_PORT, connect_timeout=3.0, snmp_port=161):
        self.host, self.port, self.connect_timeout, self.snmp_port = host, port, connect_timeout, snmp_port

    def __str__(self):
        return f"tcp://{self.host}:{self.port}"

    def connect(self):
        return socket.create_connection((self.host, self.port), timeout=self.connect_timeout)


class RfcommDevice(SocketDevice):
    """A Bluetooth printer (paired, see devices.bluetooth) on an RFCOMM channel of its serial port profile."""

    def __init__(self, address, channel=1, connect_timeout=8.0):
        self.address, self.channel, self.connect_timeout = address.upper(), channel, connect_timeout

    def __str__(self):
        return f"bt://{self.address}/{self.channel}"

    def connect(self):
        if not hasattr(socket, "AF_BLUETOOTH"):
            raise OSError("this Python has no Bluetooth sockets")
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        sock.settimeout(self.connect_timeout)
        try:
            sock.connect((self.address, self.channel))
        except OSError:
            sock.close()
            raise
        return sock


class UsbLpDevice(Device):
    """A USB printer through the kernel's usblp driver; reading needs a bidirectional printer."""

    def __init__(self, path):
        self.path = path
        self.fd = None

    def __str__(self):
        return self.path

    def open(self):
        try:
            self.fd = os.open(self.path, os.O_RDWR)
        except OSError as error:
            raise DeviceError(f"{self}: {error}") from error

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def write(self, data):
        view = memoryview(data)
        try:
            while view:
                view = view[os.write(self.fd, view):]
        except OSError as error:
            raise DeviceError(f"{self}: {error}") from error

    def read(self, size, timeout):
        """What the printer sent, waiting up to `timeout` seconds. usblp's poll reports data where there is none yet
        (the read then returns nothing): that is waited out too, else a status reply that comes a moment later is
        missed ("the printer does not answer")."""
        deadline = time.monotonic() + max(timeout, 0)
        try:
            while True:
                remaining = deadline - time.monotonic()
                ready, _, _ = select.select([self.fd], [], [], max(remaining, 0))
                chunk = os.read(self.fd, size) if ready else b""
                if chunk or remaining <= 0:
                    return chunk
                time.sleep(min(0.02, remaining))
        except OSError as error:
            raise DeviceError(f"{self}: {error}") from error


BLUETOOTH_ADDRESS = re.compile(r"^bt://((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})(?:/(\d{1,2}))?$")


def device_for(address):
    """A device for "tcp://host[:port]", "host[:port]", a device path ("/dev/usb/lp0") or a Bluetooth printer
    ("bt://AA:BB:CC:DD:EE:FF", RFCOMM channel 1, or "bt://AA:BB:CC:DD:EE:FF/2")."""
    if address.startswith("/"):
        return UsbLpDevice(address)
    if address.startswith("bt://"):
        match = BLUETOOTH_ADDRESS.match(address)
        if not match:
            raise ValueError(f"not a Bluetooth printer address: {address!r}")
        return RfcommDevice(match.group(1), int(match.group(2) or 1))
    parts = urlsplit(address if "://" in address else f"tcp://{address}")
    if parts.scheme != "tcp" or not parts.hostname:
        raise ValueError(f"not a printer address: {address!r}")
    return TcpDevice(parts.hostname, parts.port or DEFAULT_PORT)
