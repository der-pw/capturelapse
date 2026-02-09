# Changelog

All notable user-visible changes are documented here.

## 0.9.16-beta - 2026-02-09
- Gallery: switched to generated thumbnails via `/thumbs/{filename}` for faster loading.
- Snapshots now generate thumbnails immediately into `pictures/.thumbs/`.
- Thumbnails use browser cache headers for smoother scrolling/reload performance.
- Timelapse output is now stored in `pictures/timelapse/`.
- Settings: fixed focus jump while typing (live validation no longer steals focus).
- Gallery lightbox controls were cleaned up to Bootstrap-based layout utilities.
- Docs updated (`README.md`, `INSTRUCTIONS.md`) for new media folder structure and conventions.

## Template
Use this format for new entries:

```md
## <APP_VERSION> - YYYY-MM-DD
- Change 1
- Change 2
```
