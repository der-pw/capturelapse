# Changelog

All notable user-visible changes are documented here.

## 0.9.20-beta - 2026-02-10
- Camera fetching: improved resilience for unstable camera endpoints with retry-based GET handling and `Connection: close` request headers.
- Camera errors: normalized transport error text for dropped remote connections (e.g. `RemoteDisconnected`) to avoid noisy raw exception tuples in status output.

## 0.9.19-beta - 2026-02-09
- Gallery timelapse list: video names are now clickable and open an inline preview player directly inside the same modal.
- Gallery timelapse list: removed the extra preview modal to avoid stacked modal transitions.
- Gallery modal behavior: fixed horizontal background layout shift while opening/closing timelapse preview flow.
- Gallery timelapse modal: preview state is now reset on close (stop playback, clear source, hide preview block).

## 0.9.18-beta - 2026-02-09
- Dashboard controls: replaced separate Pause/Resume buttons with a single toggle button (dynamic icon and label).
- Dashboard controls: added fixed button width for both toggle and snapshot actions for consistent layout.
- i18n (de): changed action label from `Pause` to `Pausieren`.

## 0.9.16-beta - 2026-02-09
- Gallery: switched to generated thumbnails via `/thumbs/{filename}` for faster loading.
- Snapshots now generate thumbnails immediately into `pictures/.thumbs/`.
- Thumbnails use browser cache headers for smoother scrolling/reload performance.
- Timelapse output is now stored in `pictures/timelapse/`.
- Timelapse storage/search is now strict to `pictures/timelapse/` (legacy root fallback removed).
- Timelapse start flow fixed after storage refactor (correct timelapse dir initialization in create route).
- Settings: fixed focus jump while typing (live validation no longer steals focus).
- Gallery lightbox controls were cleaned up to Bootstrap-based layout utilities.
- Config fallback defaults (`ConfigModel`) were aligned with `config.default.json` to keep fresh-start behavior consistent.
- Docs updated (`README.md`, `INSTRUCTIONS.md`) for new media folder structure and conventions.

## Template
Use this format for new entries:

```md
## <APP_VERSION> - YYYY-MM-DD
- Change 1
- Change 2
```
