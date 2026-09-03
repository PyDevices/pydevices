import sys
import unittest
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _env  # noqa: E402, F401


class Uwin32ImportTests(unittest.TestCase):
    @unittest.skipIf(sys.platform == "win32", "uwin32 loads on Windows")
    def test_import_fails_off_windows(self):
        with self.assertRaises(ImportError):
            import uwin32  # noqa: F401

    @unittest.skipUnless(sys.platform == "win32", "uwin32 is Windows only")
    def test_import_on_windows(self):
        import uwin32

        self.assertTrue(hasattr(uwin32, "CreateWindowExW"))
        self.assertTrue(hasattr(uwin32, "CreateWaitableTimerExW"))
        self.assertTrue(hasattr(uwin32, "IAudioClient_Initialize_shared_pcm"))
        self.assertTrue(hasattr(uwin32, "RegisterClassExW"))
        self.assertTrue(hasattr(uwin32, "StretchDIBits"))
        self.assertTrue(hasattr(uwin32, "DefWindowProcW"))
        self.assertTrue(hasattr(uwin32, "WNDCLASSEXW"))
        self.assertTrue(hasattr(uwin32, "PAINTSTRUCT"))
        self.assertTrue(hasattr(uwin32, "RECT"))
        for name in ("bmi_rgb565", "dib_bits", "buffer_at", "VirtualAlloc", "VirtualFree", "GetPixel"):
            self.assertTrue(hasattr(uwin32, name), name)


@unittest.skipUnless(sys.platform == "win32", "uwin32 is Windows only")
class Uwin32RGB565Tests(unittest.TestCase):
    """The 16-bit BI_BITFIELDS header WinDisplay presents its framebuffer with."""

    def _header(self, bmi):
        import struct

        buf = bmi._buf if hasattr(bmi, "_buf") else memoryview(bmi).cast("B")
        return bytes(buf)

    def test_header_is_top_down_rgb565(self):
        import struct

        import uwin32

        raw = self._header(uwin32.bmi_rgb565(320, 240))
        size, width, height, planes, bits, compression, image = struct.unpack_from(
            "<IiiHHII", raw, 0
        )
        self.assertEqual(size, 40)
        self.assertEqual(width, 320)
        self.assertEqual(height, -240, "must be top-down")
        self.assertEqual(planes, 1)
        self.assertEqual(bits, 16)
        self.assertEqual(compression, uwin32.BI_BITFIELDS)
        self.assertEqual(image, 320 * 240 * 2)

    def test_channel_masks_follow_the_header(self):
        import struct

        import uwin32

        raw = self._header(uwin32.bmi_rgb565(320, 240))
        self.assertEqual(struct.unpack_from("<III", raw, 40), (0xF800, 0x07E0, 0x001F))

    def test_odd_width_rejected(self):
        import uwin32

        # RGB565 scanlines are only DWORD-aligned at even widths.
        with self.assertRaises(ValueError):
            uwin32.bmi_rgb565(321, 240)

    def test_virtual_alloc_roundtrip(self):
        import uwin32

        ptr = uwin32.VirtualAlloc(4096)
        self.assertTrue(ptr)
        try:
            view = uwin32.buffer_at(ptr, 16)
            self.assertEqual(bytes(view[:4]), b"\x00\x00\x00\x00", "pages arrive zeroed")
            view[0:4] = b"\xde\xad\xbe\xef"
            self.assertEqual(bytes(uwin32.buffer_at(ptr, 4)), b"\xde\xad\xbe\xef")
            del view
        finally:
            self.assertTrue(uwin32.VirtualFree(ptr))

    def test_dib_bits_is_an_address(self):
        import uwin32

        buf = bytearray(64)
        addr = uwin32.dib_bits(buf)
        self.assertIsInstance(addr, int)
        self.assertTrue(addr)
        # Stable across calls, so a cached base plus a scanline offset is valid.
        self.assertEqual(addr, uwin32.dib_bits(buf))


if __name__ == "__main__":
    unittest.main()


class Uwin32MidiTests(unittest.TestCase):
    """winmm MIDI bindings.

    All Windows-only: uwin32 refuses to import off Windows by design, so even
    the checks that are pure arithmetic -- message packing, the caps-name
    offset -- cannot reach the code without it. Run them with a Windows
    interpreter; under WSL they skip rather than pass, which is the honest
    outcome and not the same thing as passing.
    """


    @unittest.skipUnless(sys.platform == "win32", "uwin32 is Windows only")
    def test_message_packing_is_documented_order(self):
        # winmm wants status in the low byte, then the two data bytes. Getting
        # this backwards produces valid-looking MIDI that means something else,
        # which is the failure that does not announce itself.
        import uwin32 as w

        self.assertEqual(w.midi_unpack(0x00643C90), (0x90, 0x3C, 0x64))
        self.assertEqual(w.midi_unpack(0x0000FA), (0xFA, 0x00, 0x00))

    @unittest.skipUnless(sys.platform == "win32", "uwin32 is Windows only")
    def test_unpack_ignores_the_unused_high_byte(self):
        import uwin32 as w

        self.assertEqual(w.midi_unpack(0xFF643C90), (0x90, 0x3C, 0x64))

    @unittest.skipUnless(sys.platform == "win32", "uwin32 is Windows only")
    def test_caps_name_decodes_utf16_and_stops_at_nul(self):
        import uwin32 as w

        buf = bytearray(w.MIDIOUTCAPS_SIZE)
        name = "Espressif Device"
        raw = name.encode("utf-16-le")
        buf[w._MIDI_CAPS_NAME_OFF:w._MIDI_CAPS_NAME_OFF + len(raw)] = raw
        self.assertEqual(w._mm_caps_name(buf), name)

    @unittest.skipUnless(sys.platform == "win32", "uwin32 is Windows only")
    def test_caps_name_survives_a_full_length_field(self):
        # 32 WCHARs with no terminator is legal; the decoder must not run off
        # the end looking for one.
        import uwin32 as w

        buf = bytearray(w.MIDIINCAPS_SIZE)
        name = "X" * 32
        buf[w._MIDI_CAPS_NAME_OFF:w._MIDI_CAPS_NAME_OFF + 64] = name.encode("utf-16-le")
        self.assertEqual(w._mm_caps_name(buf), name)

    @unittest.skipUnless(sys.platform == "win32", "uwin32 is Windows only")
    def test_mm_check_raises_with_the_call_name(self):
        import uwin32 as w

        self.assertEqual(w._mm_check(0, "midiOutOpen"), 0)
        with self.assertRaises(OSError) as caught:
            w._mm_check(11, "midiOutOpen")
        self.assertIn("midiOutOpen", str(caught.exception))

    @unittest.skipUnless(sys.platform == "win32", "uwin32 is Windows only")
    def test_bindings_present(self):
        import uwin32 as w

        for name in (
            "midiOutGetNumDevs", "midiOutGetDevName", "midiOutOpen",
            "midiOutShortMsg", "midiOutReset", "midiOutClose",
            "midiInGetNumDevs", "midiInGetDevName", "midiInOpen",
            "midiInStart", "midiInStop", "midiInReset", "midiInClose",
        ):
            self.assertTrue(hasattr(w, name), name)

    @unittest.skipUnless(sys.platform == "win32", "uwin32 is Windows only")
    def test_enumeration_agrees_with_itself(self):
        # Every advertised device must yield a name; a count without a
        # readable name means the caps offset is wrong.
        import uwin32 as w

        for i in range(w.midiOutGetNumDevs()):
            self.assertIsInstance(w.midiOutGetDevName(i), str)
        for i in range(w.midiInGetNumDevs()):
            self.assertIsInstance(w.midiInGetDevName(i), str)
