import os
import random
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from apps.prescriptions.filetypes import UploadRejected, sniff, validate_upload
from apps.prescriptions.storage import FileStorage, StorageError

MB = 1024 * 1024
LIMITS = dict(max_bytes=5 * MB, max_pixels=25_000_000)


def make_png(w=4, h=3):
    def chunk(tag, body):
        c = tag + body
        return struct.pack(">I", len(body)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xff" * w for _ in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def make_jpeg(w=640, h=480):
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">H", 11) + b"\x08" + struct.pack(">HH", h, w) + b"\x01\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof + b"\xff\xda\x00\x02" + b"\xff\xd9"


PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"


class ValidateUploadTests(unittest.TestCase):
    def test_valid_png(self):
        info = validate_upload(make_png(4, 3), **LIMITS)
        self.assertEqual((info.kind, info.ext, info.width, info.height), ("png", "png", 4, 3))

    def test_valid_jpeg(self):
        info = validate_upload(make_jpeg(640, 480), **LIMITS)
        self.assertEqual((info.kind, info.ext, info.content_type, info.width, info.height),
                         ("jpeg", "jpg", "image/jpeg", 640, 480))

    def test_valid_pdf(self):
        info = validate_upload(PDF, **LIMITS)
        self.assertEqual((info.kind, info.ext, info.width), ("pdf", "pdf", None))

    def test_empty(self):
        with self.assertRaises(UploadRejected) as c:
            validate_upload(b"", **LIMITS)
        self.assertEqual(c.exception.code, "empty_file")

    def test_too_large(self):
        with self.assertRaises(UploadRejected) as c:
            validate_upload(make_png() + b"0" * (5 * MB), **LIMITS)
        self.assertEqual(c.exception.code, "file_too_large")

    def test_exactly_at_limit_is_allowed(self):
        data = PDF + b" " * (1000 - len(PDF))
        validate_upload(data, max_bytes=1000, max_pixels=10)
        with self.assertRaises(UploadRejected):
            validate_upload(data + b" ", max_bytes=1000, max_pixels=10)

    def test_spoofed_types_rejected(self):
        for name, data in [("exe", b"MZ\x90\x00" + b"\x00" * 100), ("html", b"<html><script>x</script></html>"),
                           ("zip", b"PK\x03\x04" + b"\x00" * 50), ("svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
                           ("gif", b"GIF89a" + b"\x00" * 20), ("text", b"hello")]:
            with self.subTest(name), self.assertRaises(UploadRejected) as c:
                validate_upload(data, **LIMITS)
            self.assertEqual(c.exception.code, "unsupported_type")

    def test_truncated_or_corrupt_images(self):
        for data in [b"\x89PNG\r\n\x1a\n", b"\x89PNG\r\n\x1a\n" + b"\x00" * 30, b"\xff\xd8\xff", b"\xff\xd8\xff\xe0\x00\x10JFIF",
                     make_png()[:20]]:
            with self.subTest(data[:12]), self.assertRaises(UploadRejected) as c:
                validate_upload(data, **LIMITS)
            self.assertEqual(c.exception.code, "unreadable_image")

    def test_zero_dimensions(self):
        with self.assertRaises(UploadRejected):
            validate_upload(make_png(0, 5), **LIMITS)

    def test_pixel_bomb_png_and_jpeg(self):
        for data in (make_png(20000, 20000), make_jpeg(20000, 20000)):
            with self.assertRaises(UploadRejected) as c:
                validate_upload(data, **LIMITS)
            self.assertEqual(c.exception.code, "image_too_large")

    def test_pdf_active_content_rejected(self):
        for token in (b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/RichMedia"):
            with self.subTest(token), self.assertRaises(UploadRejected) as c:
                validate_upload(PDF + b"\n1 0 obj<</S " + token + b" (x)>>", **LIMITS)
            self.assertEqual(c.exception.code, "unsafe_pdf")

    def test_pdf_similar_names_not_falsely_rejected(self):
        validate_upload(PDF + b"/JSON /Launcher".replace(b"/Launcher", b"/Information"), **LIMITS)

    def test_fuzz_never_crashes(self):
        rnd = random.Random(1234)
        seeds = [make_png(), make_jpeg(), PDF]
        for _ in range(3000):
            base = bytearray(rnd.choice(seeds))
            for _ in range(rnd.randint(0, 6)):
                if base:
                    base[rnd.randrange(len(base))] = rnd.randrange(256)
            data = bytes(base[:rnd.randint(0, len(base))]) if rnd.random() < 0.4 else bytes(base)
            try:
                validate_upload(data, **LIMITS)
            except UploadRejected:
                pass
        for _ in range(2000):
            try:
                validate_upload(rnd.randbytes(rnd.randint(0, 200)), **LIMITS)
            except UploadRejected:
                pass

    def test_sniff(self):
        self.assertEqual((sniff(make_png()), sniff(make_jpeg()), sniff(PDF), sniff(b"x")), ("png", "jpeg", "pdf", None))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "private"
        self.store = FileStorage(self.root)
        self.addCleanup(self._tmp.cleanup)

    def test_round_trip_and_hash(self):
        rel, digest = self.store.save("u1", "png", b"abc")
        self.assertTrue(rel.startswith("prescriptions/u1/") and rel.endswith(".png"))
        self.assertEqual(self.store.read(rel), b"abc")
        self.assertEqual(digest, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_names_are_random_and_never_overwrite(self):
        a, _ = self.store.save("u1", "pdf", b"x")
        b, _ = self.store.save("u1", "pdf", b"x")
        self.assertNotEqual(a, b)

    def test_never_overwrites_existing_file(self):
        from unittest import mock
        fixed = mock.Mock(hex="a" * 32)
        with mock.patch("apps.prescriptions.storage.uuid.uuid4", return_value=fixed):
            rel, _ = self.store.save("u1", "png", b"first")
            with self.assertRaises(FileExistsError):
                self.store.save("u1", "png", b"second")
        self.assertEqual(self.store.read(rel), b"first")

    def test_delete(self):
        rel, _ = self.store.save("u1", "jpg", b"x")
        self.assertTrue(self.store.delete(rel))
        self.assertFalse(self.store.delete(rel))
        with self.assertRaises(StorageError):
            self.store.read(rel)

    def test_traversal_and_absolute_paths_rejected(self):
        secret = Path(self._tmp.name) / "secret.txt"
        secret.write_text("top secret")
        self.store.save("u1", "png", b"x")
        for bad in ["../secret.txt", "prescriptions/../../secret.txt", "/etc/passwd", "\\windows\\x", "", "..",
                    "prescriptions/u1/../../../secret.txt", str(secret)]:
            with self.subTest(bad):
                with self.assertRaises(StorageError):
                    self.store.read(bad)
                with self.assertRaises(StorageError):
                    self.store.delete(bad)
        self.assertTrue(secret.exists())

    def test_non_string_path_rejected(self):
        for bad in (None, 5, b"x"):
            with self.assertRaises(StorageError):
                self.store.read(bad)

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_symlink_escape_rejected(self):
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        (outside / "f.txt").write_text("x")
        self.store.save("u1", "png", b"x")
        (self.root / "prescriptions" / "link").symlink_to(outside)
        with self.assertRaises(StorageError):
            self.store.read("prescriptions/link/f.txt")

    def test_bad_user_id_and_extension(self):
        for uid in ["", "../x", "a/b", "a b", "x" * 65, None]:
            with self.subTest(uid), self.assertRaises(StorageError):
                self.store.save(uid, "png", b"x")
        for ext in ["exe", "PNG", "png/../x", ""]:
            with self.subTest(ext), self.assertRaises(StorageError):
                self.store.save("u1", ext, b"x")

    def test_nothing_written_outside_root(self):
        before = set(Path(self._tmp.name).rglob("*"))
        self.store.save("u1", "png", b"x")
        new = set(Path(self._tmp.name).rglob("*")) - before
        for p in new:
            self.assertTrue(self.root in p.parents or p == self.root)


if __name__ == "__main__":
    unittest.main()
