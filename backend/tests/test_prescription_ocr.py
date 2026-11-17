import io
import time
import unittest
from unittest import mock

from apps.prescriptions.ocr import matcher, parser
from apps.prescriptions.ocr.errors import OcrError, OcrUnavailable
from apps.prescriptions.ocr.engines.base import OcrEngine, OcrResult

try:
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    HAVE_CV = True
except ImportError:
    HAVE_CV = False

from apps.prescriptions.ocr.engines.tesseract import TesseractEngine
HAVE_TESS = HAVE_CV and TesseractEngine().available()


class ParserTests(unittest.TestCase):
    def test_typical_lines(self):
        lines = [
            "Dr. Asha Rao MBBS", "Date: 12/10/2026", "Patient: Test Person",
            "1. Tab Paracetamol 500mg 1-0-1 x 5 days",
            "2) Cap. Amoxicillin 500 mg TDS after food for 7 days",
            "Syp Cetirizine 5mg/5ml HS qty: 1",
            "Advice: plenty of fluids",
        ]
        c = parser.parse_lines(lines)
        self.assertEqual([x["name_guess"] for x in c], ["Paracetamol", "Amoxicillin", "Cetirizine"])
        self.assertEqual(c[0]["form"], "tablet")
        self.assertEqual(c[0]["strength"]["text"], "500 mg")
        self.assertEqual(c[0]["dosage"], "1-0-1")
        self.assertEqual(c[0]["duration"], "5 days")
        self.assertEqual(c[1]["form"], "capsule")
        self.assertIn("tds", c[1]["dosage"])
        self.assertEqual(c[1]["duration"], "7 days")
        self.assertEqual(c[2]["quantity"], 1)

    def test_quantity_only_when_labelled(self):
        c = parser.parse_line("Tab Foo 500mg 10 pcs")
        self.assertIsNone(c["quantity"])

    def test_non_medicine_lines_skipped(self):
        for t in ["Dr. Rao", "Date 1/1/2026", "Patient: A", "Hospital Road", "Follow up in 2 weeks", "Rx", "", "ab", "hello world"]:
            with self.subTest(t):
                self.assertIsNone(parser.parse_line(t))

    def test_confidence_normalised_and_clamped(self):
        self.assertEqual(parser.parse_line("Tab Foobar 5mg", 87.5)["ocr_confidence"], 0.88)
        self.assertEqual(parser.parse_line("Tab Foobar 5mg", 400)["ocr_confidence"], 1.0)
        self.assertIsNone(parser.parse_line("Tab Foobar 5mg", None)["ocr_confidence"])

    def test_garbage_never_crashes_and_is_capped(self):
        import random
        rnd = random.Random(5)
        alphabet = "abcXYZ 0123456789-./:#%µ\n\t()[]{}|\\"
        for _ in range(3000):
            s = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 300)))
            parser.parse_line(s)
        many = ["Tab Drugname 5mg 1-0-1"] * 1000
        self.assertEqual(len(parser.parse_lines(many)), parser.MAX_CANDIDATES)

    def test_no_catastrophic_backtracking(self):
        nasty = ["1-" * 5000, "5 " * 5000 + "mg", "tab " * 5000, "x" * 100000 + "1-0-1", "0-" * 100 + "x", "1 . 2 . " * 3000]
        start = time.time()
        for s in nasty:
            parser.parse_line(s)
        self.assertLess(time.time() - start, 2.0)

    def test_non_dict_lines_accepted(self):
        self.assertEqual(len(parser.parse_lines(["Tab Zolpidem 10mg HS"])), 1)


PRODUCTS = [
    {"_id": "p1", "name": "Paracetamol 500 mg Tablets", "generic_name": "Paracetamol", "brand": "", "is_active": True, "requires_prescription": False},
    {"_id": "p2", "name": "Amoxicillin 500 mg Capsules", "generic_name": "Amoxicillin", "brand": "", "is_active": True, "requires_prescription": True},
    {"_id": "p3", "name": "Cetirizine 10 mg Tablets", "generic_name": "Cetirizine", "brand": "", "is_active": True, "requires_prescription": False},
    {"_id": "p4", "name": "Old Product 5 mg Tablets", "generic_name": "Oldmed", "brand": "", "is_active": False, "requires_prescription": False},
]


class MatcherTests(unittest.TestCase):
    def cand(self, name, strength=None):
        return {"name_guess": name, "strength": strength}

    def test_exact_match_is_high(self):
        s = matcher.suggest(self.cand("Paracetamol", {"value": 500.0, "unit": "mg", "text": "500 mg"}), PRODUCTS)
        self.assertEqual(s[0]["product_id"], "p1")
        self.assertEqual((s[0]["confidence"], s[0]["strength_match"]), ("high", True))

    def test_typo_still_suggested_but_not_high_certainty_claimed_as_approval(self):
        s = matcher.suggest(self.cand("Paracetmol"), PRODUCTS)
        self.assertEqual(s[0]["product_id"], "p1")

    def test_strength_mismatch_flagged_and_capped(self):
        s = matcher.suggest(self.cand("Paracetamol", {"value": 650.0, "unit": "mg", "text": "650 mg"}), PRODUCTS)
        self.assertEqual(s[0]["product_id"], "p1")
        self.assertIs(s[0]["strength_match"], False)
        self.assertLessEqual(s[0]["score"], matcher.STRENGTH_MISMATCH_CAP)
        self.assertNotEqual(s[0]["confidence"], "high")

    def test_unit_mismatch_is_mismatch(self):
        s = matcher.suggest(self.cand("Paracetamol", {"value": 500.0, "unit": "mcg", "text": "500 mcg"}), PRODUCTS)
        self.assertIs(s[0]["strength_match"], False)

    def test_inactive_never_suggested(self):
        self.assertEqual(matcher.suggest(self.cand("Oldmed"), PRODUCTS), [])

    def test_unrelated_and_empty(self):
        self.assertEqual(matcher.suggest(self.cand("Zzzzqqq"), PRODUCTS), [])
        self.assertEqual(matcher.suggest(self.cand(""), PRODUCTS), [])
        self.assertEqual(matcher.suggest(self.cand("mg tablets"), PRODUCTS), [])

    def test_at_most_three_and_sorted(self):
        many = [{"_id": f"x{i}", "name": f"Paracetamol {i} mg Tablets", "generic_name": "Paracetamol", "is_active": True} for i in range(10)]
        s = matcher.suggest(self.cand("Paracetamol"), many)
        self.assertEqual(len(s), 3)
        self.assertEqual(s, sorted(s, key=lambda x: (-x["score"], x["name"])))

    def test_no_substitution_between_different_drugs(self):
        s = matcher.suggest(self.cand("Amoxicillin"), PRODUCTS)
        self.assertEqual([x["product_id"] for x in s], ["p2"])

    def test_rx_flag_passed_through_for_display(self):
        s = matcher.suggest(self.cand("Amoxicillin"), PRODUCTS)
        self.assertTrue(s[0]["requires_prescription"])

    def test_attach_suggestions_keeps_candidate_fields(self):
        out = matcher.attach_suggestions([{"name_guess": "Cetirizine", "strength": None, "raw": "x"}], PRODUCTS)
        self.assertEqual(out[0]["raw"], "x")
        self.assertEqual(out[0]["suggestions"][0]["product_id"], "p3")


def make_text_png(lines, size=(1400, 900), angle=0.0):
    img = Image.new("L", size, 255)
    d = ImageDraw.Draw(img)
    font = None
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(path, 44)
            break
        except OSError:
            continue
    font = font or ImageFont.load_default(size=44)
    y = 60
    for line in lines:
        d.text((60, y), line, fill=0, font=font)
        y += 90
    if angle:
        img = img.rotate(angle, resample=Image.BICUBIC, fillcolor=255)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


@unittest.skipUnless(HAVE_CV, "OpenCV/numpy/Pillow not installed")
class PreprocessTests(unittest.TestCase):
    def test_output_is_binary_gray(self):
        from apps.prescriptions.ocr.preprocess import preprocess
        out = preprocess(make_text_png(["Tab Paracetamol 500mg 1-0-1"]))
        self.assertEqual(out.ndim, 2)
        self.assertTrue(set(np.unique(out)) <= {0, 255})

    def test_large_image_shrunk_small_enlarged(self):
        from apps.prescriptions.ocr import preprocess as pp
        big = np.full((4000, 5000), 255, np.uint8)
        self.assertEqual(max(pp.normalise_size(big).shape), pp.MAX_SIDE)
        small = np.full((200, 300), 255, np.uint8)
        self.assertEqual(max(pp.normalise_size(small).shape), pp.MIN_SIDE)

    def test_skew_estimated_roughly(self):
        from apps.prescriptions.ocr import preprocess as pp
        straight = pp.decode_gray(make_text_png(["Tab Paracetamol 500mg 1-0-1", "Cap Amoxicillin 500mg TDS", "Tab Cetirizine 10mg HS"]))
        tilted = pp.decode_gray(make_text_png(["Tab Paracetamol 500mg 1-0-1", "Cap Amoxicillin 500mg TDS", "Tab Cetirizine 10mg HS"], angle=4))
        self.assertLessEqual(abs(pp.estimate_skew(straight)), 1.0)
        self.assertGreaterEqual(abs(pp.estimate_skew(tilted)), 2.0)

    def test_blank_image_zero_skew(self):
        from apps.prescriptions.ocr import preprocess as pp
        self.assertEqual(pp.estimate_skew(np.full((300, 300), 255, np.uint8)), 0.0)

    def test_undecodable_bytes_raise_ocrerror(self):
        from apps.prescriptions.ocr.preprocess import preprocess
        with self.assertRaises(OcrError):
            preprocess(b"\x89PNG\r\n\x1a\nnot really a png")
        with self.assertRaises(OcrError):
            preprocess(b"")


@unittest.skipUnless(HAVE_TESS, "Tesseract not available")
class RealOcrTests(unittest.TestCase):
    def test_reads_clean_synthetic_text(self):
        from apps.prescriptions.ocr.pipeline import run_ocr
        data = make_text_png(["Tab Paracetamol 500mg 1-0-1 x 5 days", "Cap Amoxicillin 500mg TDS"])
        result = run_ocr(data, "png", TesseractEngine())
        self.assertIn("Paracetamol", result.text)
        self.assertIn("Amoxicillin", result.text)
        cands = parser.parse_lines(result.lines)
        self.assertTrue(any("paracet" in c["name_guess"].lower() for c in cands), result.text)

    def test_tilted_image_still_readable(self):
        from apps.prescriptions.ocr.pipeline import run_ocr
        data = make_text_png(["Tab Paracetamol 500mg 1-0-1", "Cap Amoxicillin 500mg TDS", "Tab Cetirizine 10mg HS"], angle=3)
        result = run_ocr(data, "png", TesseractEngine())
        self.assertIn("Paracetamol", result.text)

    def test_missing_binary_is_unavailable(self):
        engine = TesseractEngine(cmd="/nonexistent/tesseract")
        self.assertFalse(engine.available())
        with self.assertRaises(OcrUnavailable):
            engine.recognize(np.full((50, 50), 255, np.uint8))
        TesseractEngine().available()  # restore default command in the shared pytesseract module
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = "tesseract"


class FakeEngine(OcrEngine):
    name = "fake"

    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, 0

    def available(self):
        return True

    def recognize(self, image):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


@unittest.skipUnless(HAVE_CV, "OpenCV/numpy/Pillow not installed")
class PipelineTests(unittest.TestCase):
    def test_pdf_uses_injected_renderer_and_page_cap(self):
        from apps.prescriptions.ocr.pipeline import run_ocr
        page = make_text_png(["Tab Foo 5mg"])
        engine = FakeEngine(OcrResult("hello", [{"text": "hello", "confidence": 90.0}], "fake"))
        result = run_ocr(b"%PDF-", "pdf", engine, max_pages=2, pdf_renderer=lambda d, n: [page] * 5)
        self.assertEqual(engine.calls, 2)
        self.assertEqual(result.text, "hello\n\nhello")

    def test_pdf_without_renderer_library_is_unavailable(self):
        from apps.prescriptions.ocr.pipeline import run_ocr
        from apps.prescriptions.ocr.pdf import render_pdf_pages
        try:
            import fitz  # noqa
            self.skipTest("PyMuPDF is installed here")
        except ImportError:
            pass
        with self.assertRaises(OcrUnavailable):
            run_ocr(b"%PDF-1.4", "pdf", FakeEngine(), pdf_renderer=render_pdf_pages)

    def test_engine_errors_propagate(self):
        from apps.prescriptions.ocr.pipeline import run_ocr
        with self.assertRaises(OcrError):
            run_ocr(make_text_png(["x"]), "png", FakeEngine(error=OcrError("boom")))

    def test_empty_pdf_render(self):
        from apps.prescriptions.ocr.pipeline import run_ocr
        with self.assertRaises(OcrError):
            run_ocr(b"%PDF-", "pdf", FakeEngine(), pdf_renderer=lambda d, n: [])


class EngineFactoryTests(unittest.TestCase):
    def test_factory(self):
        from apps.prescriptions.ocr.engines import get_engine
        self.assertEqual(get_engine("tesseract").name, "tesseract")
        with self.assertRaises(ValueError):
            get_engine("nope")


if __name__ == "__main__":
    unittest.main()
