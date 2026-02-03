// app/static/js/app.js
// Shared helpers for CaptureLapse frontends
(function () {
  const CaptureLapse = {};

  CaptureLapse.fetchJson = async function fetchJson(url, options = {}, { timeoutMs = 10000 } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, {
        ...options,
        signal: controller.signal,
        headers: {
          Accept: 'application/json, text/plain, */*',
          ...(options.headers || {}),
        },
      });
      clearTimeout(timer);

      const contentType = response.headers.get('content-type') || '';
      let data = null;
      if (contentType.includes('application/json')) {
        data = await response.json();
      } else if (contentType.startsWith('text/')) {
        data = await response.text();
      }

      if (!response.ok) {
        const error = new Error(`Request failed with status ${response.status}`);
        error.response = response;
        error.data = data;
        throw error;
      }

      return { data, response };
    } catch (err) {
      clearTimeout(timer);
      throw err;
    }
  };

  CaptureLapse.showAlert = function showAlert(
    target,
    { message, type = 'info', dismissMs = 4000, closable = true, className = '' }
  ) {
    if (!target) return null;
    target.innerHTML = '';
    const wrapper = document.createElement('div');
    const baseClasses = [`alert`, `alert-${type}`];
    if (closable) {
      baseClasses.push('alert-dismissible');
    }
    baseClasses.push('fade', 'show');
    if (className) {
      baseClasses.push(className);
    }
    wrapper.className = baseClasses.join(' ');
    wrapper.role = 'alert';
    wrapper.textContent = message;

    if (closable) {
      const close = document.createElement('button');
      close.type = 'button';
      close.className = 'btn-close';
      close.dataset.bsDismiss = 'alert';
      wrapper.appendChild(close);
    }

    target.appendChild(wrapper);

    if (dismissMs) {
      setTimeout(() => wrapper.remove(), dismissMs);
    }
    return wrapper;
  };

  CaptureLapse.showGlobalStatus = function showGlobalStatus(message, type = 'info', { sticky = false } = {}) {
    const target = document.getElementById('global-status');
    if (!target) return null;
    return CaptureLapse.showAlert(target, {
      message,
      type,
      dismissMs: sticky ? 0 : 2500,
      closable: false,
      className: 'py-2 px-3',
    });
  };

  CaptureLapse.startTimelapseStatus = function startTimelapseStatus() {
    const target = document.getElementById('global-status');
    if (!target) return;

        const labelRunning = target.dataset.labelRunning || 'Rendering...';
        const labelDone = target.dataset.labelDone || 'Timelapse finished.';
        const labelError = target.dataset.labelError || 'Timelapse failed.';
        const labelFinalizing = target.dataset.labelFinalizing || 'Finalizing...';
    const watchKey = 'capturelapse_timelapse_watch';
    const runningPollMs = 3000;
    const idlePollMs = 10000;
    const errorStampKey = 'capturelapse_timelapse_error_stamp';
    let lastErrorStamp = sessionStorage.getItem(errorStampKey);

    CaptureLapse.timelapseGlobalStatusActive = true;

    function showGlobal(message, type, { sticky = false } = {}) {
      CaptureLapse.showGlobalStatus(message, type, { sticky });
    }

    function clearGlobal() {
      target.innerHTML = '';
    }

    const poll = async () => {
      let nextDelay = idlePollMs;
      try {
        const res = await fetch('/timelapse/status');
        if (!res.ok) {
          setTimeout(poll, nextDelay);
          return;
        }
        const data = await res.json();
        if (data.state === 'running') {
          const percentRaw = Number(data.progress);
          const percent = Number.isFinite(percentRaw) ? Math.max(0, Math.min(100, percentRaw)) : null;
          const suffix = percent !== null
            ? (percent >= 100 ? ` ${labelFinalizing}` : ` ${percent}%`)
            : '';
          showGlobal(`${labelRunning}${suffix}`, 'info', { sticky: true });
          sessionStorage.setItem(watchKey, '1');
          nextDelay = runningPollMs;
          setTimeout(poll, nextDelay);
          return;
        }

        const shouldNotify = sessionStorage.getItem(watchKey) === '1';
        if (data.state === 'done') {
          if (shouldNotify) {
            showGlobal(labelDone, 'success');
          }
          sessionStorage.removeItem(watchKey);
        } else if (data.state === 'error') {
          const stamp = data.finished_at || data.message || 'error';
          if (shouldNotify || stamp !== lastErrorStamp) {
            showGlobal(labelError, 'danger');
          }
          lastErrorStamp = stamp;
          sessionStorage.setItem(errorStampKey, stamp);
          sessionStorage.removeItem(watchKey);
        } else {
          if (!shouldNotify) {
            clearGlobal();
          }
          sessionStorage.removeItem(watchKey);
        }
      } catch (err) {
        // Ignore transient errors; retry on next interval.
      }
      setTimeout(poll, nextDelay);
    };

    poll();
  };

  window.CaptureLapse = CaptureLapse;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', CaptureLapse.startTimelapseStatus);
  } else {
    CaptureLapse.startTimelapseStatus();
  }
})();
