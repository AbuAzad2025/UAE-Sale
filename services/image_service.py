"""Product image processing: resize, thumbnail, and safe storage.

static/js/shop.js uploads a product image with:

    POST /warehouse/api/upload_product_image
      file      = the image
      subdir    = 'products'
      max_side  = '1200'   # longest edge, in pixels
      quality   = '82'     # JPEG quality

and reads back `{ok, url, thumb_url}`, where `url` is the value to store on
the product's image field and `thumb_url` is the preview shown in the form.

The file itself is validated by utils.helpers.save_uploaded_file, which
enforces the extension allowlist, the size cap, the double-extension guard
and the polyglot-header check. This module adds the pixel work on top: it
re-opens the saved file with Pillow, which is also what proves the upload is
really an image and not something that merely has an image extension.
"""

import io
import os

from flask import current_app
from PIL import Image, UnidentifiedImageError

MAX_PIXELS = 40_000_000

_SUPPORTED_FORMATS = ("JPEG", "PNG", "WEBP")


class ImageProcessingError(Exception):
    """تعذّر معالجة الصورة المرفوعة."""


def _clamp(value, default, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def process_and_store(
    file, subdir="products", max_side=1200, quality=82, thumb_side=400
):
    """خزّن الصورة، صغّرها، وأنشئ مصغّرة.

    يعيد (url, thumb_url) - المساران نسبيان إلى مجلد static.
    """
    if not file or not file.filename:
        raise ImageProcessingError("لم يتم إرفاق ملف")

    from utils.helpers import save_uploaded_file

    image_extensions = {"images"}
    try:
        configured = current_app.config.get("ALLOWED_UPLOAD_EXTENSIONS", {})
        if isinstance(configured, dict):
            image_extensions = set(configured.get("images", image_extensions))
    except Exception:
        pass

    relative_path = save_uploaded_file(
        file, subdir, allowed_extensions=image_extensions
    )

    if not relative_path:
        raise ImageProcessingError("تعذّر حفظ الملف")

    absolute_path = os.path.join(current_app.static_folder, relative_path)

    try:
        with Image.open(absolute_path) as image:
            image.load()

            if image.format not in _SUPPORTED_FORMATS:
                raise ImageProcessingError(f"صيغة الصورة غير مدعومة: {image.format}")

            if image.width * image.height > MAX_PIXELS:
                raise ImageProcessingError("أبعاد الصورة كبيرة جداً")

            max_side = _clamp(max_side, 1200, 64, 4096)
            quality = _clamp(quality, 82, 40, 95)
            thumb_side = _clamp(thumb_side, 400, 64, 2048)

            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")

            if max(image.size) > max_side:
                image.thumbnail((max_side, max_side), Image.LANCZOS)

            stem, _ = os.path.splitext(absolute_path)
            final_path = f"{stem}.jpg"
            image.convert("RGB").save(
                final_path, "JPEG", quality=quality, optimize=True
            )

            thumb = image.copy()
            thumb.thumbnail((thumb_side, thumb_side), Image.LANCZOS)
            thumb_path = f"{stem}_thumb.jpg"
            thumb.convert("RGB").save(
                thumb_path, "JPEG", quality=quality, optimize=True
            )
    except ImageProcessingError:
        _cleanup(absolute_path)
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        _cleanup(absolute_path)
        raise ImageProcessingError(f"تعذّر قراءة الصورة: {exc}") from exc

    if final_path != absolute_path:
        _cleanup(absolute_path)

    return (
        os.path.relpath(final_path, current_app.static_folder).replace("\\", "/"),
        os.path.relpath(thumb_path, current_app.static_folder).replace("\\", "/"),
    )


def _cleanup(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        current_app.logger.warning("Could not remove %s", path)


def read_image_bytes(file):
    """يقرأ ملف الصورة كاملاً في الذاكرة (للاختبارات)."""
    data = file.read()
    return io.BytesIO(data)
