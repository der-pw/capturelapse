// app/static/js/dashboard.js
// Dashboard interactions: SSE with reconnect, status polling and AJAX actions
(function () {
  const root = document.getElementById('dashboard-app');
  if (!root) return;

  const { fetchJson } = window.CaptureLapse || {};
  if (!fetchJson) {
    console.warn('CaptureLapse helpers not loaded');
    return;
  }

  const qs = (id) => document.getElementById(id);
  const els = {
    latestImg: qs('latest-img'),
    lastTime: qs('last-time'),
    statusText: qs('status-text'),
    time: qs('time'),
    sunrise: qs('sunrise'),
    sunset: qs('sunset'),
    count: qs('count'),
    scheduleStart: qs('schedule-start'),
    scheduleEnd: qs('schedule-end'),
    nextSnapshot: qs('next-snapshot'),
  };

  const messages = {
    lastLabel: root.dataset.lastLabel || 'Last image',
    cameraErrorPrefix: root.dataset.cameraErrorPrefix || 'Camera error',
    cameraErrorSnapshot: root.dataset.cameraErrorSnapshot || 'Snapshot failed',
    statusPaused: root.dataset.statusPaused || 'Recording paused',
    statusRunning: root.dataset.statusRunning || 'Recording running',
    statusRunningInterval: root.dataset.statusRunningInterval || 'Recording running with {seconds} second interval',
    statusWaiting: root.dataset.statusWaiting || 'Waiting for active time window',
    statusConfigReloaded: root.dataset.statusConfigReloaded || 'Configuration reloaded',
    statusCameraError: root.dataset.statusCameraError || 'Camera access error',
    statusLastSuccess: root.dataset.statusLastSuccess || 'Last image captured successfully',
    nextSnapshot: root.dataset.nextSnapshotLabel || 'Next snapshot',
    statusReconnecting: root.dataset.statusReconnecting || 'Reconnecting to live updates …',
    statusFailed: root.dataset.statusFailed || 'Status could not be loaded',
    actionError: root.dataset.actionError || 'Action failed',
    pauseLabel: root.dataset.labelPause || 'Pause',
    resumeLabel: root.dataset.labelResume || 'Resume',
  };

  const intervalSeconds = parseInt(root.dataset.intervalSeconds || '', 10);

  const scheduleLocale = root.dataset.locale || navigator.language || 'de';
  const scheduleStart = root.dataset.scheduleStart || '';
  const scheduleEnd = root.dataset.scheduleEnd || '';

  const parseDate = (value) => {
    if (!value) return null;
    const parts = value.split('-').map((item) => parseInt(item, 10));
    if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) return null;
    return new Date(parts[0], parts[1] - 1, parts[2]);
  };

  const formatDate = (value) => {
    const date = parseDate(value);
    if (!date) return value || '';
    try {
      return new Intl.DateTimeFormat(scheduleLocale, {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
      }).format(date);
    } catch (_) {
      return value;
    }
  };

  const applyScheduleText = () => {
    if (els.scheduleStart) {
      els.scheduleStart.textContent = scheduleStart ? formatDate(scheduleStart) : '--';
    }
    if (els.scheduleEnd) {
      els.scheduleEnd.textContent = scheduleEnd ? formatDate(scheduleEnd) : '--';
    }
  };

  const EMPTY_TIME = '---';
  let imageCount = 0;
  let lastSnapshot = null;
  let statusRevertTimer = null;
  let es = null;
  let esRetryDelay = 2000;
  let sseConnected = false;
  let pollTimer = null;
  const POLL_INTERVAL_MS = 60000;
  let cameraErrorActive = false;
  let cameraErrorSource = null; // 'snapshot' | 'health'
  let isPaused = false;

  function updatePauseToggleButton() {
    const btn = qs('btn-toggle-pause');
    if (!btn) return;
    const icon = btn.querySelector('i');
    const label = btn.querySelector('span');
    btn.classList.toggle('btn-warning', !isPaused);
    btn.classList.toggle('btn-success', isPaused);
    if (icon) {
      icon.classList.toggle('fa-pause', !isPaused);
      icon.classList.toggle('fa-play', isPaused);
    }
    if (label) {
      label.textContent = isPaused ? messages.resumeLabel : messages.pauseLabel;
    }
  }

  const bust = (u) => `${u}${u.includes('?') ? '&' : '?'}t=${Date.now()}`;
  const fallbackImage = '/static/img/capturelapse.jpg';

  if (els.latestImg) {
    els.latestImg.addEventListener('error', () => {
      const src = els.latestImg.getAttribute('src') || '';
      if (src.includes('last.jpg')) {
        els.latestImg.src = fallbackImage;
      }
    });
    const applyFallbackIfBroken = () => {
      if (!els.latestImg) return;
      if (els.latestImg.complete && els.latestImg.naturalWidth === 0) {
        const src = els.latestImg.getAttribute('src') || '';
        if (src.includes('last.jpg')) {
          els.latestImg.src = fallbackImage;
        }
      }
    };
    if (document.readyState === 'loading') {
      window.addEventListener('load', applyFallbackIfBroken, { once: true });
    } else {
      setTimeout(applyFallbackIfBroken, 0);
    }
  }

  const parseLegacyDateTime = (value) => {
    if (!value) return null;
    const match = value.match(/^(\d{2})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})/);
    if (!match) return null;
    const [, day, month, year, hour, minute] = match;
    return new Date(2000 + Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute));
  };

  const formatDateTime = (date) => {
    if (!date || Number.isNaN(date.getTime())) return '';
    try {
      return new Intl.DateTimeFormat(scheduleLocale, {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      }).format(date);
    } catch (_) {
      return '';
    }
  };

  const updateLastTime = (timestamp, fullTimestamp, isoTimestamp) => {
    if (!els.lastTime) return;
    const valueEl = els.lastTime.querySelector('.value');
    let value = '';
    if (isoTimestamp) {
      value = formatDateTime(new Date(isoTimestamp));
    } else if (fullTimestamp) {
      const legacyDate = parseLegacyDateTime(fullTimestamp);
      value = legacyDate ? formatDateTime(legacyDate) : fullTimestamp;
    } else if (timestamp) {
      value = timestamp;
    }
    const finalValue = value || EMPTY_TIME;
    if (valueEl) {
      valueEl.textContent = finalValue;
    } else {
      els.lastTime.textContent = `${messages.lastLabel}: ${finalValue}`;
    }
    els.lastTime.style.display = '';
  };

  const updateNextSnapshot = (isoTimestamp) => {
    if (!els.nextSnapshot) return;
    const valueEl = els.nextSnapshot.querySelector('.value');
    let value = '';
    if (isoTimestamp) {
      value = formatDateTime(new Date(isoTimestamp));
    }
    const finalValue = value || EMPTY_TIME;
    if (valueEl) {
      valueEl.textContent = finalValue;
    } else {
      els.nextSnapshot.textContent = `${messages.nextSnapshot || 'Next snapshot'}: ${finalValue}`;
    }
  };

  function setStatus(message, revertMs, isError = false) {
    if (!els.statusText) return;
    els.statusText.textContent = message || '';
    els.statusText.classList.toggle('text-danger', Boolean(isError));
    if (statusRevertTimer) {
      clearTimeout(statusRevertTimer);
      statusRevertTimer = null;
    }
    if (revertMs) {
      statusRevertTimer = setTimeout(() => {
        fetchStatus();
      }, revertMs);
    }
  }

  function formatCameraError(errorInfo) {
    if (!errorInfo) return '';
    const detail = (errorInfo.code === 'snapshot_failed' && messages.cameraErrorSnapshot) || errorInfo.message || '';
    const suffix = detail ? `: ${detail}` : '';
    return `${messages.cameraErrorPrefix}${suffix}`;
  }

  function formatCameraHealth(healthInfo) {
    if (!healthInfo || healthInfo.status !== 'error') return '';
    const detail = healthInfo.message || healthInfo.code || '';
    const suffix = detail ? `: ${detail}` : '';
    return `${messages.cameraErrorPrefix}${suffix}`;
  }

  function refreshImage() {
    if (!els.latestImg) return;
    els.latestImg.src = bust('/static/img/last.jpg');
    els.latestImg.style.display = '';
  }

  async function fetchStatus({ syncImage = false } = {}) {
    try {
      const { data } = await fetchJson('/status');
      if (!data) throw new Error('Missing status payload');

      if (typeof data.count === 'number') {
        imageCount = data.count;
        if (els.count) els.count.textContent = imageCount;
      }

      const newSnapshot = data.last_snapshot || null;
      const newSnapshotTooltip = data.last_snapshot_tooltip || newSnapshot;
      const snapshotChanged = newSnapshot && newSnapshot !== lastSnapshot;
      lastSnapshot = newSnapshot;

      updateLastTime(newSnapshot, newSnapshotTooltip, data.last_snapshot_iso);
      updateNextSnapshot(data.next_snapshot_iso);

      if (syncImage && snapshotChanged) {
        refreshImage();
      }

      if (els.sunrise) els.sunrise.textContent = data.sunrise || '--:--';
      if (els.sunset) els.sunset.textContent = data.sunset || '--:--';

      const cameraErrorMsg = formatCameraError(data.camera_error || null);
      const cameraHealthMsg = formatCameraHealth(data.camera_health || null);
      if (cameraErrorMsg) {
        cameraErrorActive = true;
        cameraErrorSource = 'snapshot';
        setStatus(cameraErrorMsg, null, true);
      } else if (cameraHealthMsg) {
        cameraErrorActive = true;
        cameraErrorSource = 'health';
        setStatus(cameraHealthMsg, null, true);
      } else if (data.paused === true) {
        isPaused = true;
        updatePauseToggleButton();
        cameraErrorActive = false;
        cameraErrorSource = null;
        setStatus(messages.statusPaused);
      } else if (data.active === true) {
        isPaused = false;
        updatePauseToggleButton();
        cameraErrorActive = false;
        cameraErrorSource = null;
        if (Number.isFinite(intervalSeconds) && intervalSeconds > 0) {
          setStatus(messages.statusRunningInterval.replace('{seconds}', intervalSeconds));
        } else {
          setStatus(messages.statusRunning);
        }
      } else {
        isPaused = false;
        updatePauseToggleButton();
        cameraErrorActive = false;
        cameraErrorSource = null;
        setStatus(messages.statusWaiting);
      }
    } catch (err) {
      console.warn('Status could not be loaded', err);
      setStatus(messages.statusFailed, null, true);
    }
  }

  function handleSnapshotUpdate(timestamp, fullTimestamp, isoTimestamp) {
    imageCount += 1;
    if (els.count) els.count.textContent = imageCount;
    if (timestamp) lastSnapshot = timestamp;
    refreshImage();
    updateLastTime(timestamp, fullTimestamp, isoTimestamp);
    cameraErrorActive = false;
    cameraErrorSource = null;
    setStatus(messages.statusLastSuccess, 5000);
  }

  function handleStatusUpdate(status) {
    if (!status || cameraErrorActive) return;
    let revert = false;
    if (status === 'paused') {
      isPaused = true;
      updatePauseToggleButton();
      setStatus(messages.statusPaused);
    } else if (status === 'running') {
      isPaused = false;
      updatePauseToggleButton();
      if (Number.isFinite(intervalSeconds) && intervalSeconds > 0) {
        setStatus(messages.statusRunningInterval.replace('{seconds}', intervalSeconds));
      } else {
        setStatus(messages.statusRunning);
      }
    } else if (status === 'waiting_window') {
      setStatus(messages.statusWaiting);
    } else if (status === 'config_reloaded') {
      setStatus(messages.statusConfigReloaded);
      revert = true;
    }

    if (revert) {
      statusRevertTimer = setTimeout(() => fetchStatus(), 5000);
    }
  }

  function connectSse() {
    if (es) {
      es.close();
      es = null;
    }

    es = new EventSource('/events');
    esRetryDelay = 2000;

    es.onopen = () => {
      esRetryDelay = 2000;
      sseConnected = true;
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    };

    es.onerror = () => {
      sseConnected = false;
      setStatus(messages.statusReconnecting);
      if (es) {
        es.close();
        es = null;
      }
      setTimeout(connectSse, esRetryDelay);
      esRetryDelay = Math.min(esRetryDelay * 1.5, 30000);
      if (!pollTimer) {
        pollTimer = setInterval(() => fetchStatus({ syncImage: true }), POLL_INTERVAL_MS);
      }
    };

    es.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === 'snapshot' && payload.filename) {
          handleSnapshotUpdate(payload.timestamp, payload.timestamp_full, payload.timestamp_iso);
        }

        if (payload.type === 'status') {
          handleStatusUpdate(payload.status);
        }

        if (payload.type === 'next_snapshot') {
          updateNextSnapshot(payload.next_snapshot_iso);
        }

        if (payload.type === 'camera_error') {
          const cameraMsg = formatCameraError({ code: payload.code, message: payload.message }) || messages.statusCameraError;
          cameraErrorActive = true;
          cameraErrorSource = 'snapshot';
          setStatus(cameraMsg, 8000, true);
        }
        if (payload.type === 'camera_health') {
          const healthMsg = formatCameraHealth(payload);
          if (healthMsg) {
            cameraErrorActive = true;
            cameraErrorSource = 'health';
            setStatus(healthMsg, null, true);
          } else if (cameraErrorActive && cameraErrorSource === 'health') {
            cameraErrorActive = false;
            cameraErrorSource = null;
            fetchStatus();
          }
        }
      } catch (err) {
        console.warn('SSE parse error', event.data);
      }
    };
  }

  async function sendAction(path) {
    const btn = path === 'pause' || path === 'resume' ? qs('btn-toggle-pause') : qs('btn-snapshot');
    if (btn) btn.disabled = true;
    try {
      await fetchJson(`/action/${path}`, { method: 'POST' }, { timeoutMs: 15000 });
      if (path === 'pause') {
        isPaused = true;
        updatePauseToggleButton();
        setStatus(messages.statusPaused);
      } else if (path === 'resume') {
        isPaused = false;
        updatePauseToggleButton();
        setStatus(messages.statusRunning);
      }
    } catch (err) {
      console.warn(`Action ${path} failed`, err);
      setStatus(messages.actionError, 4000);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function bindActions() {
    const pauseToggle = qs('btn-toggle-pause');
    const snapshot = qs('btn-snapshot');
    if (pauseToggle) {
      pauseToggle.addEventListener('click', () => sendAction(isPaused ? 'resume' : 'pause'));
    }
    if (snapshot) snapshot.addEventListener('click', () => sendAction('snapshot'));
  }

  function startClock() {
    if (!els.time) return;
    let clockTimer = null;
    const updateClock = () => {
      const now = new Date();
      els.time.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    };
    const startTimer = () => {
      if (clockTimer) return;
      updateClock();
      clockTimer = setInterval(updateClock, 1000);
    };
    const stopTimer = () => {
      if (!clockTimer) return;
      clearInterval(clockTimer);
      clockTimer = null;
    };
    const handleVisibility = () => {
      if (document.hidden) {
        stopTimer();
      } else {
        startTimer();
      }
    };

    document.addEventListener('visibilitychange', handleVisibility);
    startTimer();
  }

  applyScheduleText();
  startClock();
  if (window.bootstrap && window.bootstrap.Tooltip) {
    const tooltipTargets = root.querySelectorAll('[data-bs-toggle="tooltip"]');
    tooltipTargets.forEach((el) => {
      window.bootstrap.Tooltip.getOrCreateInstance(el);
    });
  }
  fetchStatus();
  connectSse();
  bindActions();
  if (!sseConnected && !pollTimer) {
    pollTimer = setInterval(() => fetchStatus({ syncImage: true }), POLL_INTERVAL_MS);
  }
})();


