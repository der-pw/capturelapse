from pathlib import Path

from PIL import Image, ImageOps

from app.logger_utils import log

THUMBS_DIR_NAME = ".thumbs"
THUMB_MAX_EDGE = 320
THUMB_QUALITY = 80


def thumbs_dir_for(save_dir: Path) -> Path:
    return save_dir / THUMBS_DIR_NAME


def thumbnail_path_for(source_path: Path) -> Path:
    return source_path.parent / THUMBS_DIR_NAME / f"{source_path.name}.jpg"


def _resampling_filter():
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:
        return Image.LANCZOS


def create_thumbnail(source_path: Path, max_edge: int = THUMB_MAX_EDGE) -> Path | None:
    """Create or overwrite thumbnail for an image file."""
    thumb_path = thumbnail_path_for(source_path)
    thumb_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with Image.open(source_path) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((max_edge, max_edge), _resampling_filter())
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            tmp_path = thumb_path.with_suffix(thumb_path.suffix + ".tmp")
            img.save(tmp_path, format="JPEG", quality=THUMB_QUALITY, optimize=True)
            tmp_path.replace(thumb_path)
        return thumb_path
    except Exception as e:
        log("warn", f"Thumbnail generation failed for {source_path.name}: {e}")
        return None


def ensure_thumbnail(source_path: Path, max_edge: int = THUMB_MAX_EDGE) -> Path | None:
    """Ensure a thumbnail exists and is up to date for source image."""
    thumb_path = thumbnail_path_for(source_path)
    try:
        if thumb_path.exists() and thumb_path.stat().st_mtime >= source_path.stat().st_mtime:
            return thumb_path
    except Exception:
        pass
    return create_thumbnail(source_path, max_edge=max_edge)


def delete_thumbnail_for(source_path: Path) -> None:
    """Best-effort thumbnail cleanup for a source image."""
    thumb_path = thumbnail_path_for(source_path)
    try:
        if thumb_path.exists():
            thumb_path.unlink()
    except Exception:
        pass
