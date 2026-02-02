# TODO

## Performance & Load
- Optionally refresh cached stats in a periodic background task (e.g., every 60s) instead of scanning on each request.
- Consider pausing/throttling the client clock update when the tab is hidden to reduce background wakeups.

## UX / Status Messaging
- Keep unified status line but clarify source (healthcheck vs snapshot) if needed.
- Consider showing reconnect/status warnings only after multiple consecutive failures and tune threshold as needed.
- Consider holiday calendars (e.g., via Python `holidays`) to skip capture on public holidays.

## Browser Load
- 1s clock updates in inactive tabs can be throttled via `visibilitychange`.

## Healthcheck
- Expose healthcheck status on UI more explicitly if users want to distinguish reachability vs snapshot failures.
- Camera error: Snapshot failed when cam is behind auth.

## Auth / Security
- Add optional API token support (e.g., header-based token for non-UI clients).
- [x] Store access passwords as hashes instead of plaintext (bcrypt).
- [x] Add rate limiting / login throttling for `/login` (simple in-memory).
- [ ] Set and document `CAPTURELAPSE_SESSION_SECRET` for stable sessions.
- Ensure HTTPS is used in production (reverse proxy guidance).

## Video Render
- Consider queueing multiple render jobs or explicit job cancellation.
- Improve large-range performance (streaming/iterating without full in-memory list).
- Make ordering deterministic when mtime collisions occur (tie-breaker by filename).



