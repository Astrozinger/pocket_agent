"""
screen.py — let the agent look at what's on the screen.

Two engines, tried in order:
  1. OCR (mss + pytesseract + Pillow) -> actual text, works on any window
  2. Vision model                 -> a screenshot handed to Gemini
If neither is installed the tool says so plainly instead of failing silently.
"""

import os
import tempfile


def _grab_png(path: str = None) -> str:
    """Screenshot the whole desktop and return the file path."""
    import mss
    from PIL import Image

    path = path or os.path.join(tempfile.gettempdir(), "pocket_screen.png")
    with mss.mss() as sct:
        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        shot = sct.grab(monitor)
        img = Image.frombytes("RGB", shot.size, shot.rgb)
        # keep it small enough for a vision model and for OCR speed
        if img.width > 1600:
            ratio = 1600 / img.width
            img = img.resize((1600, int(img.height * ratio)))
        img.save(path, "PNG")
    return path


def screenshot() -> str:
    """Capture the screen to a PNG file."""
    try:
        return _grab_png()
    except Exception as e:
        raise RuntimeError("Could not capture the screen: %s" % e)


def ocr_text(max_chars: int = 3000) -> str:
    """Read the text currently visible on screen."""
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        raise RuntimeError(
            "Screen reading needs two free tools. Install them once:\n"
            "  pip install pillow pytesseract\n"
            "  and the Tesseract engine: https://github.com/UB-Mannheim/tesseract/wiki"
        )
    path = screenshot()
    try:
        text = pytesseract.image_to_string(Image.open(path))
    except Exception as e:
        msg = str(e).lower()
        if "tesseract is not installed" in msg or "no such file" in msg:
            raise RuntimeError(
                "Tesseract isn't installed. Get it here (free): "
                "https://github.com/UB-Mannheim/tesseract/wiki — then restart Pocket."
            )
        raise
    text = " ".join(text.split())
    return text[:max_chars] if text else ""
