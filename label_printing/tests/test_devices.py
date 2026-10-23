from django.test import SimpleTestCase
from PIL import Image, ImageChops, ImageDraw

from .. import drivers, simulator
from ..devices import brother, zebra
from ..devices.io import TcpDevice, device_for, UsbLpDevice
from ..devices.run import Result, query_status, run_job
from .helpers import SimulatedPrinters


def tape_image(width=160, pins=70):
    image = Image.new("1", (width, pins), 1)
    draw = ImageDraw.Draw(image)
    draw.rectangle((5, 3, 40, pins - 4), fill=0)
    draw.line((50, 0, width - 1, pins - 1), fill=0)
    return image


class StatusParsingTests(SimpleTestCase):
    def test_brother_status_record(self):
        state = simulator.PrinterState(errors=["cover_open"], tape_mm=24)
        status = brother.parse(simulator.brother_status(state))
        self.assertEqual(status["errors"], ["cover_open"])
        self.assertEqual(status["media_width_mm"], 24)
        self.assertEqual(status["media_type"], "laminated")
        self.assertFalse(status["ok"])

    def test_brother_records_are_found_between_other_bytes(self):
        record = simulator.brother_status(simulator.PrinterState())
        found, rest = brother.split_records(b"\x00junk" + record + record[:10])
        self.assertEqual(found, [record])
        self.assertEqual(rest, record[:10])

    def test_zebra_host_status(self):
        state = simulator.PrinterState(errors=["paper_out", "head_open"])
        status = zebra.parse(simulator.zebra_status(state, formats=2, remaining=5))
        self.assertEqual(status["errors"], ["paper_out", "head_open"])
        self.assertEqual((status["formats_in_buffer"], status["labels_remaining"], status["phase"]), (2, 5, "printing"))
        with self.assertRaises(ValueError):
            zebra.parse(b"\x02nothing\x03")

    def test_result_travels_as_json_data(self):
        result = Result("failed", "wrong_tape", {"loaded_mm": 24, "expected_mm": 12}, {"errors": []})
        self.assertEqual(Result.from_dict({**result.to_dict(), "unknown": 1}), result)

    def test_device_addresses(self):
        self.assertIsInstance(device_for("/dev/usb/lp0"), UsbLpDevice)
        device = device_for("tcp://printer.local:9101")
        self.assertEqual((device.host, device.port), ("printer.local", 9101))
        self.assertEqual(device_for("10.0.0.5").port, 9100)
        with self.assertRaises(ValueError):
            device_for("usb://0x04f9:0x2060")


class RunJobTests(SimulatedPrinters, SimpleTestCase):
    def brother_job(self, copies=1):
        return drivers.ptouch_job("E550W", 12, [tape_image()], copies)

    def run_brother(self, payload, pages, **kwargs):
        return run_job(TcpDevice("127.0.0.1", self.brother_server.port), "ptouch", payload,
                       expected_tape_mm=12, pages=pages, timeout=5, **kwargs)

    def test_brother_job_is_printed_and_confirmed(self):
        payload, pages = self.brother_job(copies=2)
        result = self.run_brother(payload, pages)
        self.assertEqual((result.status, result.code), ("done", ""))
        self.assertEqual(result.printer_status["media_width_mm"], 12)
        self.assertEqual(len(self.brother_output.printed), 2)

    def test_brother_wrong_tape_prints_nothing(self):
        self.brother_state.tape_mm = 24
        result = self.run_brother(*self.brother_job())
        self.assertEqual((result.status, result.code), ("failed", "wrong_tape"))
        self.assertEqual(result.detail, {"loaded_mm": 24, "expected_mm": 12})
        self.assertFalse(result.retryable)
        self.assertEqual(self.brother_output.printed, [])

    def test_brother_error_before_printing(self):
        self.brother_state.errors = ["cover_open"]
        result = self.run_brother(*self.brother_job())
        self.assertEqual((result.status, result.code), ("failed", "cover_open"))
        self.assertEqual(self.brother_output.printed, [])

    def test_silent_printer_counts_as_not_answering(self):
        self.brother_state.silent = True
        result = self.run_brother(*self.brother_job())
        self.assertEqual((result.status, result.code, result.retryable), ("failed", "no_response", True))

    def test_without_status_check_the_job_is_only_sent(self):
        self.brother_state.silent = True
        result = self.run_brother(*self.brother_job(), check_status=False)
        self.assertEqual((result.status, result.code), ("sent", ""))

    def test_unreachable_printer_can_be_tried_again(self):
        server = simulator.start("brother")
        port = server.port
        server.stop()
        result = run_job(TcpDevice("127.0.0.1", port), "ptouch", b"x", timeout=1)
        self.assertEqual((result.status, result.code, result.retryable), ("failed", "unreachable", True))

    def test_zebra_job_is_printed_and_confirmed(self):
        image = Image.new("1", (456, 256), 1)
        payload = drivers.zpl_job([drivers.zpl_raster_label(image, copies=2)])
        result = run_job(TcpDevice("127.0.0.1", self.zebra_server.port), "zpl", payload, pages=2, timeout=5)
        self.assertEqual((result.status, result.code), ("done", ""))
        self.assertEqual([name.rsplit(".", 1)[1] for name, _data in self.zebra_output.printed], ["zpl"])

    def test_zebra_paper_out(self):
        self.zebra_state.errors = ["paper_out"]
        result = run_job(TcpDevice("127.0.0.1", self.zebra_server.port), "zpl", b"^XA^XZ", timeout=5)
        self.assertEqual((result.status, result.code), ("failed", "paper_out"))
        status = query_status(TcpDevice("127.0.0.1", self.zebra_server.port), "zpl")
        self.assertEqual(status.printer_status["errors"], ["paper_out"])


class SimulatorTests(SimpleTestCase):
    def test_brother_raster_decodes_to_the_label_image(self):
        image = tape_image()
        payload, pages = drivers.ptouch_job("E550W", 12, [image, image.transpose(Image.FLIP_LEFT_RIGHT)])
        decoded = simulator.decode_brother(payload)
        self.assertEqual(pages, 2)
        self.assertEqual([page.size for page in decoded], [image.size, image.size])
        self.assertIsNone(ImageChops.difference(decoded[0].convert("L"), image.convert("L")).getbbox())

    def test_p900_raster_decodes_too(self):
        pins = drivers.ptouch_print_pins("P900W", 24)
        image = tape_image(pins=pins)
        decoded, = simulator.decode_brother(drivers.ptouch_job("P900W", 24, [image])[0])
        self.assertIsNone(ImageChops.difference(decoded.convert("L"), image.convert("L")).getbbox())

    def test_zebra_renders_through_the_renderer(self):
        rendered = []

        def render(zpl, dpi, count):
            rendered.append((zpl, dpi, count))
            return b"%PDF", "pdf"

        output = simulator.Output()
        server = simulator.start("zebra", output=output, render=render, seconds_per_label=0)
        self.addCleanup(server.stop)
        zpl = "^XA^PW456^LL256^PQ3^XZ"
        result = run_job(TcpDevice("127.0.0.1", server.port), "zpl", zpl.encode(), timeout=5)
        self.assertEqual(result.status, "done")
        self.assertEqual(rendered, [(zpl, 203, 3)])
        self.assertEqual([name.rsplit(".", 1)[1] for name, _data in output.printed], ["zpl", "pdf"])

    def test_zpl_label_size_for_labelary(self):
        self.assertEqual(simulator.zpl_size_inches("^XA^PW406^LL203^XZ", 203), (2.0, 1.0))
        self.assertEqual(simulator.zpl_label_count("^XA^PQ2^XZ^XA^XZ"), 3)


class ZplGraphicTests(SimpleTestCase):
    def test_raster_label_decodes_to_the_image(self):
        image = tape_image(width=456, pins=256)
        zpl = drivers.zpl_raster_label(image, copies=2, offset=(3, 4), darkness=5)
        self.assertTrue(zpl.startswith("^XA^PW456^LL256^LH3,4^MD5^FO0,0^GFA,14592,14592,57,"))
        self.assertTrue(zpl.endswith("^FS^PQ2^XZ"))
        decoded, = simulator.zpl_graphics(zpl)
        self.assertIsNone(ImageChops.difference(decoded.convert("L"), image.convert("L")).getbbox())
        self.assertEqual(simulator.zpl_graphics(drivers.zpl_raster_label(Image.new("1", (8, 1), 1)))[0].getpixel((0, 0)), 255)


class BrotherSnmpTests(SimpleTestCase):
    """Like a PT-P900W on the network: no status on the print port, the status record over SNMP."""

    def setUp(self):
        self.state = simulator.PrinterState(name="brother", tape_mm=12, inband_status=False)
        self.output = simulator.Output()
        self.server = simulator.start("brother", state=self.state, output=self.output, snmp_port=0,
                                      seconds_per_page=0.3)
        self.addCleanup(self.server.stop)

    def device(self):
        return TcpDevice("127.0.0.1", self.server.port, snmp_port=self.server.snmp.port)

    def test_snmp_get(self):
        from ..devices import snmp

        record = snmp.get("127.0.0.1", brother.STATUS_OID, port=self.server.snmp.port)
        self.assertEqual(brother.parse(record)["media_width_mm"], 12)
        self.assertIsNone(snmp.get("127.0.0.1", brother.STATUS_OID, port=1, timeout=0.2))

    def test_status_and_printing_over_snmp(self):
        status = query_status(self.device(), "ptouch")
        self.assertEqual((status.status, status.printer_status["tape_color"]), ("done", "weiß"))
        payload, pages = drivers.ptouch_job("E550W", 12, [tape_image()], copies=2)
        result = run_job(self.device(), "ptouch", payload, expected_tape_mm=12, pages=pages, timeout=10)
        self.assertEqual((result.status, result.code), ("done", ""))
        self.assertEqual(len(self.output.printed), 2)

    def test_wrong_tape_over_snmp(self):
        self.state.tape_mm = 24
        result = run_job(self.device(), "ptouch", b"x", expected_tape_mm=12, timeout=5)
        self.assertEqual((result.status, result.code), ("failed", "wrong_tape"))

    def test_without_snmp_or_inband_status(self):
        device = TcpDevice("127.0.0.1", self.server.port, snmp_port=1)
        result = run_job(device, "ptouch", b"x", timeout=5)
        self.assertEqual((result.status, result.code), ("failed", "no_response"))


class QualityTests(SimpleTestCase):
    def advanced_mode(self, data):
        return data[data.find(b"\x1biK") + 3]

    def print_length(self, data):
        start = data.find(b"\x1biz")
        return int.from_bytes(data[start + 7:start + 11], "little")

    def test_brother_draft_and_high_resolution(self):
        image = tape_image(width=100)
        standard, _ = drivers.ptouch_job("E550W", 12, [image])
        draft, _ = drivers.ptouch_job("E550W", 12, [image], quality="draft")
        wide = image.resize((200, image.height), Image.NEAREST)
        high, _ = drivers.ptouch_job("E550W", 12, [wide], quality="high")
        self.assertEqual(self.advanced_mode(draft), self.advanced_mode(standard) | 0x01)
        self.assertEqual(self.advanced_mode(high), self.advanced_mode(standard) | 0x40)
        self.assertEqual((self.print_length(standard), self.print_length(high)), (100, 200))
        decoded, = simulator.decode_brother(high)  # every line once, not doubled
        self.assertIsNone(ImageChops.difference(decoded.convert("L"), wide.convert("L")).getbbox())

    def test_zebra_speed(self):
        image = Image.new("1", (16, 8), 1)
        self.assertIn("^PR2^FO", drivers.zpl_raster_label(image, quality="high"))
        self.assertIn("^PR6^FO", drivers.zpl_raster_label(image, quality="draft"))
        self.assertNotIn("^PR", drivers.zpl_raster_label(image))
        self.assertEqual(drivers.zpl_with_quality("^XA^FDx^FS^XZ", "high"), "^XA^PR2^FDx^FS^XZ")

    def test_squeeze_keeps_thin_lines(self):
        from .. import render

        image = Image.new("1", (4, 4), 1)
        image.putpixel((1, 1), 0)  # one dot on an odd row
        squeezed = render.squeeze(image, 2)
        self.assertEqual(squeezed.size, (4, 2))
        self.assertEqual(squeezed.getpixel((1, 0)), 0)
        self.assertEqual(squeezed.getpixel((0, 0)), 255)


class BrotherOffsetTests(SimpleTestCase):
    def first_black_pin(self, data):
        pages = []
        simulator.BrotherStream(on_page=pages.append).feed(data)
        line = pages[0]["lines"][0]
        return next(pin for pin in range(len(line) * 8) if line[pin // 8] & (0x80 >> (pin % 8)))

    def test_offset_moves_the_print_area_across_the_tape(self):
        image = Image.new("1", (8, 150), 1)
        ImageDraw.Draw(image).line((0, 0, 7, 0), fill=0)  # the top row
        for offset, pin in ((0, 197), (6, 203), (-6, 191), (-999, 0)):
            with self.subTest(offset=offset):
                self.assertEqual(self.first_black_pin(drivers.ptouch_job("P900W", 12, [image], offset=offset)[0]), pin)
