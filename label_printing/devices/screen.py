"""
A touch screen for the print agent (the Raspberry Pi Touch Display, 800 × 480, or any screen with touch): pygame
(apt python3-pygame, SDL2) draws full-screen straight on the display (KMS/DRM, no desktop) and reads the touches.
Draws the items laid out by label_printing/touch.py; the backlight is switched in /sys/class/backlight.

pygame is imported only here, so the agent runs without it (without screen). The service's user needs the groups
video (the display; the backlight once ops/raspberry-pi/update.sh allowed it) and input (the touches).
"""
import glob
import logging
import os

log = logging.getLogger("label_printing.screen")

FONTS = {False: ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",),
         True: ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",)}
PALETTE = {
    "background": (17, 20, 24), "header": (30, 36, 43), "card": (30, 36, 43), "alert": (61, 46, 16),
    "text": (242, 244, 246), "muted": (154, 164, 174), "ok": (63, 185, 80), "warn": (227, 179, 65),
    "error": (248, 81, 73), "note": (47, 129, 247), "shade": (0, 0, 0, 170), "dialog": (40, 47, 56),
    "normal": (55, 64, 75), "primary": (31, 111, 235), "danger": (200, 45, 40), "tab": (30, 36, 43),
    "tab_active": (47, 129, 247), "disabled": (45, 50, 57), "disabled_text": (110, 118, 128),
}


class NoScreen(Exception):
    pass


class TouchScreen:
    def __init__(self, rotation=0, driver=None):
        """rotation 180: for a display mounted upside down. driver: SDL's video driver (default: kmsdrm on a Pi
        without desktop, else what SDL finds)."""
        if driver:
            os.environ["SDL_VIDEODRIVER"] = driver
        elif not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY") and os.path.exists("/dev/dri"):
            os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        try:
            import pygame
        except ImportError as error:
            raise NoScreen(f"pygame missing ({error}): install python3-pygame") from None
        self.pygame = pygame
        try:
            pygame.display.init()
            pygame.font.init()
            info = pygame.display.Info()
            full = os.environ.get("SDL_VIDEODRIVER") == "kmsdrm"
            if full and (info.current_w <= 0 or info.current_h <= 0):
                raise NoScreen("no display connected")
            self.window = pygame.display.set_mode((info.current_w, info.current_h) if full else (800, 480),
                                                  pygame.FULLSCREEN if full else 0)
        except pygame.error as error:
            raise NoScreen(f"no display: {error}") from None
        pygame.mouse.set_visible(False)
        self.size = self.window.get_size()
        self.rotation = rotation
        self.canvas = pygame.Surface(self.size)
        self.fonts = {}
        self.touch = self.has_touch()
        self.backlights = glob.glob("/sys/class/backlight/*")
        log.info("touch screen %d × %d (%s), touch: %s, backlight: %s", *self.size, pygame.display.get_driver(),
                 self.touch, ", ".join(self.backlights) or "none")

    def has_touch(self):
        try:
            from pygame._sdl2 import touch

            return touch.get_num_devices() > 0
        except Exception:
            return False

    # ------------------------------------------------------------ text

    def font(self, size, bold=False):
        key = (size, bold)
        if key not in self.fonts:
            path = next((path for path in FONTS[bold] if os.path.exists(path)), None)
            font = self.pygame.font.Font(path, size)
            if path is None and bold:
                font.set_bold(True)
            self.fonts[key] = font
        return self.fonts[key]

    def measure(self, text, size, bold=False):
        return self.font(size, bold).size(text)[0]

    def fit(self, text, size, bold, width):
        """The text, cut with … to the width."""
        font = self.font(size, bold)
        if font.size(text)[0] <= width:
            return text
        while text and font.size(text + "…")[0] > width:
            text = text[:-1]
        return text + "…"

    # ------------------------------------------------------------ touches

    def events(self):
        """The touches since the last call: [("down" | "move" | "up", x, y)] in screen pixels (as drawn: turned
        back for rotation 180). The mouse counts where there is no touch screen (trying it out on a computer)."""
        pygame, found = self.pygame, []
        width, height = self.size
        for event in pygame.event.get():
            if event.type in (pygame.FINGERDOWN, pygame.FINGERMOTION, pygame.FINGERUP):
                kind = {pygame.FINGERDOWN: "down", pygame.FINGERMOTION: "move", pygame.FINGERUP: "up"}[event.type]
                found.append((kind, int(event.x * width), int(event.y * height)))
            elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEMOTION, pygame.MOUSEBUTTONUP):
                if getattr(event, "touch", False) or self.touch:
                    continue  # SDL also sends touches as mouse events
                if event.type == pygame.MOUSEMOTION and not event.buttons[0]:
                    continue
                kind = {pygame.MOUSEBUTTONDOWN: "down", pygame.MOUSEMOTION: "move", pygame.MOUSEBUTTONUP: "up"}[event.type]
                found.append((kind, *event.pos))
            elif event.type == pygame.QUIT:
                raise SystemExit
        if self.rotation == 180:
            found = [(kind, width - 1 - x, height - 1 - y) for kind, x, y in found]
        return found

    # ------------------------------------------------------------ drawing

    def draw(self, frame, scroll=0):
        """Draw a touch.Frame: the content scrolled by `scroll` pixels between header and tabs."""
        from ..touch import CONTENT_BOTTOM, CONTENT_TOP

        pygame, canvas = self.pygame, self.canvas
        canvas.fill(PALETTE["background"])
        area = pygame.Rect(0, CONTENT_TOP, self.size[0], CONTENT_BOTTOM - CONTENT_TOP)
        canvas.set_clip(area)
        for item in frame.content:
            self.draw_item(item, 0, CONTENT_TOP - scroll)
        canvas.set_clip(None)
        self.scrollbar(area, frame.height, scroll, self.size[0] - 5)
        for item in frame.fixed + frame.overlay:
            self.draw_item(item, 0, 0)
        if frame.choices_area is not None:  # a dialog's list, scrolled in its own area
            choices = pygame.Rect(frame.choices_area)
            canvas.set_clip(choices)
            for item in frame.choices:
                self.draw_item(item, choices.left, choices.top - frame.choices_scroll)
            canvas.set_clip(None)
            self.scrollbar(choices, frame.choices_height, frame.choices_scroll, choices.right + 7)
        shown = pygame.transform.rotate(canvas, 180) if self.rotation == 180 else canvas
        self.window.blit(shown, (0, 0))
        pygame.display.flip()

    def scrollbar(self, area, height, scroll, x):
        """Where in a list taller than its area: a thin bar at x."""
        if height > area.height:
            bar = max(24, area.height * area.height // height)
            top = area.top + (area.height - bar) * scroll // max(1, height - area.height)
            self.pygame.draw.rect(self.canvas, PALETTE["muted"], (x, top, 3, bar), border_radius=2)

    def draw_item(self, item, dx, dy):
        pygame, canvas = self.pygame, self.canvas
        x, y = item.x + dx, item.y + dy
        if item.kind == "box":
            color = PALETTE.get(item.color, PALETTE["card"])
            if len(color) == 4:  # see-through: the shade behind a dialog
                shade = pygame.Surface((item.w, item.h), pygame.SRCALPHA)
                shade.fill(color)
                canvas.blit(shade, (x, y))
            else:
                pygame.draw.rect(canvas, color, (x, y, item.w, item.h), border_radius=10)
        elif item.kind == "text":
            self.draw_text(item.text, x, y, item.w, item.size, PALETTE.get(item.color, PALETTE["text"]), item.bold,
                           item.align)
        elif item.kind == "button":
            if item.style == "flat":
                return
            enabled = item.action is not None
            color = PALETTE[item.style if enabled else "disabled"]
            radius = 0 if item.style.startswith("tab") else 10
            pygame.draw.rect(canvas, color, (x, y, item.w, item.h), border_radius=radius)
            if item.style == "tab":
                pygame.draw.line(canvas, PALETTE["background"], (x, y), (x, y + item.h), 2)
            text_color = PALETTE["text"] if enabled else PALETTE["disabled_text"]
            height = self.font(item.size, True).get_height()
            self.draw_text(item.label, x + 8, y + (item.h - height) // 2, item.w - 16, item.size, text_color, True,
                           "center")

    def draw_text(self, text, x, y, width, size, color, bold, align):
        text = self.fit(text, size, bold, width)
        image = self.font(size, bold).render(text, True, color)
        if align == "center":
            x += (width - image.get_width()) // 2
        elif align == "right":
            x += width - image.get_width()
        self.canvas.blit(image, (x, y))

    # ------------------------------------------------------------ backlight

    def backlight(self, on):
        """Switch the backlight (bl_power: 0 on, 4 off); where that is not allowed, the screen goes black."""
        done = False
        for path in self.backlights:
            try:
                with open(os.path.join(path, "bl_power"), "w") as file:
                    file.write("0" if on else "4")
                done = True
            except OSError as error:
                log.debug("backlight %s: %s", path, error)
        if not done and not on:
            self.window.fill((0, 0, 0))
            self.pygame.display.flip()
