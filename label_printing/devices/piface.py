"""
PiFace Control & Display 2: a 16 × 2 character LCD (HD44780) and eight switches on an MCP23S17 port
expander on SPI bus 0, chip select 1 (/dev/spidev0.1). Needs python3-spidev and SPI switched on
(dtparam=spi=on in config.txt, see ops/raspberry-pi/prepare-boot.sh).

Port A: the switches (pulled up, pressed = 0): 0–4 the five buttons below the display, from the left,
5 the navigation switch pressed, 6 and 7 pushed left and right.
Port B: the display in 4-bit mode: bits 0–3 data D4–D7, 4 enable, 5 read/write, 6 register select, 7 backlight
(pin map of the pifacecad library).
"""
import time

IODIRA, IODIRB, IOCON, GPPUA, GPIOA, GPIOB = 0x00, 0x01, 0x0A, 0x0C, 0x12, 0x13
WRITE, READ = 0x40, 0x41  # opcode of hardware address 0
IOCON_HAEN = 0x08
ENABLE, RW, RS, BACKLIGHT = 0x10, 0x20, 0x40, 0x80
CLEAR, ENTRY_LEFT, DISPLAY_ON, FUNCTION_4BIT_2LINE, SET_DDRAM, SET_CGRAM = 0x01, 0x06, 0x0C, 0x28, 0x80, 0x40
ROW_OFFSETS = (0x00, 0x40)
BUTTONS, PRESS, LEFT, RIGHT = (0, 1, 2, 3, 4), 5, 6, 7

# Characters of the display's ROM (A00) for letters it has, the rest as plain letters
ROM = {"ä": 0xE1, "ö": 0xEF, "ü": 0xF5, "ß": 0xE2, "°": 0xDF, "→": 0x7E, "←": 0x7F, "·": 0xA5}
PLAIN = {"Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "×": "x", "–": "-", "—": "-", "…": "...", "„": '"', "“": '"', "”": '"',
         "€": "EUR"}
# Own characters (CGRAM 0–7, 5 × 8 dots): a check mark, a cross, pause, play
GLYPHS = {
    "✓": (0x00, 0x01, 0x03, 0x16, 0x1C, 0x08, 0x00, 0x00),
    "✗": (0x00, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x00, 0x00),
    "⏸": (0x00, 0x1B, 0x1B, 0x1B, 0x1B, 0x1B, 0x00, 0x00),
    "▶": (0x00, 0x08, 0x0C, 0x0E, 0x0C, 0x08, 0x00, 0x00),
}
GLYPH_CODES = {char: code for code, char in enumerate(GLYPHS)}


def encode(text, width=16):
    """A line as the display's character codes, cut or padded to `width`."""
    codes = []
    for char in text:
        if char in GLYPH_CODES:
            codes.append(GLYPH_CODES[char])
        elif char in ROM:
            codes.append(ROM[char])
        elif char in PLAIN:
            codes.extend(ord(c) for c in PLAIN[char])
        elif 0x20 <= ord(char) < 0x7E and char not in "\\~":
            codes.append(ord(char))
        else:
            codes.append(ord("?"))
    return (codes + [0x20] * width)[:width]


class NoDisplay(Exception):
    """No PiFace Control & Display answers (or spidev is missing)."""


class PiFaceCAD:
    WIDTH, LINES = 16, 2

    def __init__(self, spi=None, bus=0, chip_select=1):
        if spi is None:
            try:
                import spidev
            except ImportError as error:
                raise NoDisplay(f"{error} (install python3-spidev)") from error
            spi = spidev.SpiDev()
            try:
                spi.open(bus, chip_select)
            except OSError as error:
                raise NoDisplay(f"/dev/spidev{bus}.{chip_select}: {error} (SPI switched on?)") from error
            spi.mode, spi.max_speed_hz = 0, 4000000
        self.spi = spi
        self.port_b = 0
        self.shown = [None] * self.LINES
        self.write_register(IOCON, IOCON_HAEN)
        if self.read_register(IOCON) & 0x7F != IOCON_HAEN:  # nothing answers on the bus: no board
            raise NoDisplay("no PiFace Control & Display on SPI")
        self.write_register(IODIRA, 0xFF)
        self.write_register(GPPUA, 0xFF)
        self.write_register(GPIOB, 0)
        self.write_register(IODIRB, 0x00)
        self.init_display()

    def write_register(self, register, value):
        self.spi.xfer2([WRITE, register, value])

    def read_register(self, register):
        return self.spi.xfer2([READ, register, 0])[2]

    # ------------------------------------------------------------ switches

    def switches(self):
        """The switches pressed now, as a set of their numbers (0–7)."""
        value = ~self.read_register(GPIOA) & 0xFF
        return {number for number in range(8) if value & (1 << number)}

    # ------------------------------------------------------------ display

    def set_port_b(self, value):
        self.port_b = value
        self.write_register(GPIOB, value)

    def nibble(self, value, rs):
        base = (self.port_b & BACKLIGHT) | (RS if rs else 0) | (value & 0x0F)
        self.set_port_b(base | ENABLE)
        self.set_port_b(base)  # data is taken on the falling edge; SPI is slower than the 450 ns pulse

    def send(self, byte, rs=False):
        self.nibble(byte >> 4, rs)
        self.nibble(byte, rs)
        time.sleep(0.00005)

    def init_display(self):
        time.sleep(0.015)
        for _ in range(3):
            self.nibble(0x3, False)
            time.sleep(0.0045)
        self.nibble(0x2, False)
        for command in (FUNCTION_4BIT_2LINE, DISPLAY_ON, ENTRY_LEFT):
            self.send(command)
        self.send(CLEAR)
        time.sleep(0.003)
        self.send(SET_CGRAM)
        for glyph in GLYPHS.values():
            for row in glyph:
                self.send(row, rs=True)
        self.backlight(True)

    def backlight(self, on):
        self.set_port_b((self.port_b | BACKLIGHT) if on else (self.port_b & ~BACKLIGHT))

    def show(self, lines):
        """Show up to two lines; only lines that changed are written."""
        for row in range(self.LINES):
            codes = encode(lines[row] if row < len(lines) else "", self.WIDTH)
            if codes == self.shown[row]:
                continue
            self.send(SET_DDRAM | ROW_OFFSETS[row])
            for code in codes:
                self.send(code, rs=True)
            self.shown[row] = codes


SWITCH_NAMES = {0: "Taste 1", 1: "Taste 2", 2: "Taste 3", 3: "Taste 4", 4: "Taste 5", PRESS: "Wippe gedrueckt",
                LEFT: "Wippe: zurueck", RIGHT: "Wippe: vor"}


def main():
    """Button test: shows which switch the agent sees pressed. Stop the agent first (it uses the display):
    sudo systemctl stop label-agent; cd /opt/label-agent; python3 -m label_printing.devices.piface"""
    display = PiFaceCAD()
    display.show(["Tastentest", "Taste druecken"])
    print("Press the buttons; Ctrl-C ends.")
    last = set()
    try:
        while True:
            pressed = display.switches()
            if pressed != last and pressed:
                text = ", ".join(f"{SWITCH_NAMES[number]} ({number})" for number in sorted(pressed))
                print(text)
                display.show([f"Schalter {','.join(str(number) for number in sorted(pressed))}",
                              SWITCH_NAMES[min(pressed)]])
            last = pressed
            time.sleep(0.05)
    except KeyboardInterrupt:
        display.show(["", ""])
        display.backlight(False)


if __name__ == "__main__":
    main()
