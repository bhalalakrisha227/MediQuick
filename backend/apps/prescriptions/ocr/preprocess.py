"""
Image clean-up before OCR, using OpenCV. OpenCV/numpy are imported lazily so the rest of
the app (and its tests) still work on a machine where they are not installed.

Steps: decode -> grayscale -> size normalise -> light denoise -> deskew -> adaptive threshold.
Only APIs that behave the same in OpenCV 4.x and 5.x are used.
"""
from .errors import OcrError, OcrUnavailable

MAX_SIDE = 3000       # larger photos are shrunk (speed + memory)
MIN_SIDE = 1000       # small images are enlarged (Tesseract does poorly on tiny text)
MAX_SKEW_DEGREES = 10
SKEW_STEP = 0.5


def _libs():
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise OcrUnavailable("OpenCV/numpy are not installed.") from exc
    return cv2, np


def decode_gray(data: bytes):
    cv2, np = _libs()
    if not data:
        raise OcrError("The image could not be decoded.")
    try:
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    except cv2.error as exc:
        raise OcrError("The image could not be decoded.") from exc
    if image is None or image.size == 0:
        raise OcrError("The image could not be decoded.")
    return image


def normalise_size(gray):
    cv2, _ = _libs()
    h, w = gray.shape[:2]
    longest = max(h, w)
    if longest > MAX_SIDE:
        scale = MAX_SIDE / longest
        return cv2.resize(gray, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    if longest < MIN_SIDE:
        scale = MIN_SIDE / longest
        return cv2.resize(gray, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_CUBIC)
    return gray


def estimate_skew(gray) -> float:
    """Skew in degrees (positive = text rotated counter-clockwise), by maximising row-profile variance.

    Uses a small copy so it is fast. Returns 0.0 when the page has too little ink to judge.
    """
    cv2, np = _libs()
    h, w = gray.shape[:2]
    scale = 600 / max(h, w) if max(h, w) > 600 else 1.0
    small = cv2.resize(gray, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA) if scale < 1 else gray
    _, ink = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if int(np.count_nonzero(ink)) < 50:
        return 0.0
    sh, sw = ink.shape[:2]
    centre = (sw / 2, sh / 2)
    best_angle, best_score = 0.0, -1.0
    steps = int(MAX_SKEW_DEGREES / SKEW_STEP)
    for i in range(-steps, steps + 1):
        angle = i * SKEW_STEP
        matrix = cv2.getRotationMatrix2D(centre, angle, 1.0)
        rotated = cv2.warpAffine(ink, matrix, (sw, sh), flags=cv2.INTER_NEAREST, borderValue=0)
        profile = rotated.sum(axis=1, dtype=np.float64)
        score = float(np.var(profile))
        if score > best_score + 1e-9:
            best_angle, best_score = angle, score
    return best_angle


def rotate(gray, angle: float):
    if abs(angle) < 0.25:
        return gray
    cv2, _ = _libs()
    h, w = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(gray, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def preprocess_array(gray):
    cv2, _ = _libs()
    gray = normalise_size(gray)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    gray = rotate(gray, estimate_skew(gray))
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)


def preprocess(data: bytes):
    """Image bytes -> a clean black-on-white numpy array ready for OCR."""
    cv2, _ = _libs()
    try:
        return preprocess_array(decode_gray(data))
    except cv2.error as exc:
        raise OcrError("The image could not be processed.") from exc
