// app/static/js/settings.js
// Progressive enhancement for the settings form
(function () {
  const form = document.getElementById('settings-form');
  if (!form) return;

  const statusBox = document.getElementById('settings-status') || document.getElementById('global-status');
  const { fetchJson, showAlert } = window.CaptureLapse || {};

  const successMsg = form.dataset.saveSuccess || 'Einstellungen gespeichert';
  const errorMsg = form.dataset.saveError || 'Speichern fehlgeschlagen';
  const geoSuccessMsg = form.dataset.geoSuccess || 'Koordinaten aus Browserstandort übernommen';
  const geoUnsupportedMsg = form.dataset.geoUnsupported || 'Browser-Geolokalisierung wird nicht unterstützt';
  const geoDeniedMsg = form.dataset.geoDenied || 'Standortfreigabe verweigert';
  const geoErrorMsg = form.dataset.geoError || 'Standort konnte nicht ermittelt werden';
  const dateRangeErrorMsg = form.dataset.validateDateRange || 'Start date must not be after end date';
  const camUrlErrorMsg = form.dataset.validateCamUrl || 'Snapshot URL is required';
  const intervalErrorMsg = form.dataset.validateInterval || 'Interval must be a positive number';
  const authUsernameErrorMsg = form.dataset.validateAuthUsername || 'Username is required for authentication';
  const authPasswordErrorMsg = form.dataset.validateAuthPassword || 'Password is required for authentication';
  const latRequiredMsg = form.dataset.validateLatRequired || 'Latitude is required when Astral is enabled';
  const lonRequiredMsg = form.dataset.validateLonRequired || 'Longitude is required when Astral is enabled';
  const latRangeMsg = form.dataset.validateLatRange || 'Latitude must be between -90 and 90';
  const lonRangeMsg = form.dataset.validateLonRange || 'Longitude must be between -180 and 180';

  const latInput = form.querySelector('input[name="CITY_LAT"]');
  const lonInput = form.querySelector('input[name="CITY_LON"]');
  const tzInput = form.querySelector('[name="CITY_TZ"]');
  const langSelect = form.querySelector('select[name="LANGUAGE"]');
  const camUrlInput = form.querySelector('input[name="CAM_URL"]');
  const intervalInput = form.querySelector('input[name="INTERVAL_SECONDS"]');
  const authTypeInput = form.querySelector('select[name="AUTH_TYPE"]');
  const usernameInput = form.querySelector('input[name="USERNAME"]');
  const passwordInput = form.querySelector('input[name="PASSWORD"]');
  const useAstralInput = form.querySelector('input[name="USE_ASTRAL"]');
  const geoBtn = document.getElementById('geo-browser-btn');
  const clearDateBtn = document.getElementById('clear-date-range');
  const dateFromInput = form.querySelector('input[name="DATE_FROM"]');
  const dateToInput = form.querySelector('input[name="DATE_TO"]');

  const showSavedFromQuery = () => {
    if (!showAlert || !statusBox) return;
    const params = new URLSearchParams(window.location.search || '');
    if (params.get('saved') !== null) {
      showAlert(statusBox, {
        message: successMsg,
        type: 'success',
        dismissMs: 2500,
        closable: false,
        className: 'py-2 px-3 mb-0',
      });
    }
  };

  function validateDateRange(showMessage) {
    if (!dateFromInput || !dateToInput) return true;
    if (!dateFromInput.value || !dateToInput.value) {
      dateFromInput.setCustomValidity('');
      dateToInput.setCustomValidity('');
      return true;
    }
    if (dateFromInput.value > dateToInput.value) {
      dateToInput.setCustomValidity(dateRangeErrorMsg);
      if (showMessage) {
        if (showAlert) {
          showAlert(statusBox, {
            message: dateRangeErrorMsg,
            type: 'warning',
            dismissMs: 6000,
            closable: false,
            className: 'py-2 px-3 mb-0',
          });
        }
        if (typeof dateToInput.reportValidity === 'function') {
          dateToInput.reportValidity();
        } else if (showMessage) {
          alert(dateRangeErrorMsg);
        }
      }
      return false;
    }
    dateFromInput.setCustomValidity('');
    dateToInput.setCustomValidity('');
    return true;
  }

  function showValidationMessage(message, input, showMessage) {
    if (!message) return;
    if (input && typeof input.reportValidity === 'function') {
      input.reportValidity();
    }
    if (!showMessage) return;
    if (showAlert) {
      showAlert(statusBox, {
        message,
        type: 'warning',
        dismissMs: 6000,
        closable: false,
        className: 'py-2 px-3 mb-0',
      });
    } else {
      alert(message);
    }
  }

  function validateForm(showMessage) {
    const errors = [];

    if (camUrlInput) {
      const value = (camUrlInput.value || '').trim();
      if (!value) {
        camUrlInput.setCustomValidity(camUrlErrorMsg);
        errors.push({ input: camUrlInput, message: camUrlErrorMsg });
      } else {
        camUrlInput.setCustomValidity('');
      }
    }

    if (intervalInput) {
      const value = parseFloat(intervalInput.value || '');
      if (!Number.isFinite(value) || value <= 0) {
        intervalInput.setCustomValidity(intervalErrorMsg);
        errors.push({ input: intervalInput, message: intervalErrorMsg });
      } else {
        intervalInput.setCustomValidity('');
      }
    }

    if (authTypeInput && authTypeInput.value !== 'none') {
      if (usernameInput) {
        const value = (usernameInput.value || '').trim();
        if (!value) {
          usernameInput.setCustomValidity(authUsernameErrorMsg);
          errors.push({ input: usernameInput, message: authUsernameErrorMsg });
        } else {
          usernameInput.setCustomValidity('');
        }
      }
      if (passwordInput) {
        const value = (passwordInput.value || '').trim();
        if (!value) {
          passwordInput.setCustomValidity(authPasswordErrorMsg);
          errors.push({ input: passwordInput, message: authPasswordErrorMsg });
        } else {
          passwordInput.setCustomValidity('');
        }
      }
    } else {
      if (usernameInput) usernameInput.setCustomValidity('');
      if (passwordInput) passwordInput.setCustomValidity('');
    }

    if (useAstralInput && useAstralInput.checked) {
      if (latInput) {
        const raw = (latInput.value || '').trim();
        const value = raw === '' ? NaN : Number(raw.replace(',', '.'));
        if (raw === '') {
          latInput.setCustomValidity(latRequiredMsg);
          errors.push({ input: latInput, message: latRequiredMsg });
        } else if (!Number.isFinite(value) || value < -90 || value > 90) {
          latInput.setCustomValidity(latRangeMsg);
          errors.push({ input: latInput, message: latRangeMsg });
        } else {
          latInput.setCustomValidity('');
        }
      }
      if (lonInput) {
        const raw = (lonInput.value || '').trim();
        const value = raw === '' ? NaN : Number(raw.replace(',', '.'));
        if (raw === '') {
          lonInput.setCustomValidity(lonRequiredMsg);
          errors.push({ input: lonInput, message: lonRequiredMsg });
        } else if (!Number.isFinite(value) || value < -180 || value > 180) {
          lonInput.setCustomValidity(lonRangeMsg);
          errors.push({ input: lonInput, message: lonRangeMsg });
        } else {
          lonInput.setCustomValidity('');
        }
      }
    } else {
      if (latInput) latInput.setCustomValidity('');
      if (lonInput) lonInput.setCustomValidity('');
    }

    const dateRangeOk = validateDateRange(false);
    if (!dateRangeOk) {
      errors.push({ input: dateToInput, message: dateRangeErrorMsg });
    }

    if (errors.length > 0) {
      const first = errors[0];
      showValidationMessage(first.message, first.input, showMessage);
      return false;
    }
    return true;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!validateForm(true)) {
      return;
    }
    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn) submitBtn.disabled = true;

    try {
      const formData = new FormData(form);
      const result = await fetchJson('/update', { method: 'POST', body: formData }, { timeoutMs: 15000 });
      const currentLang = (formData.get('LANGUAGE') || (langSelect ? langSelect.value : null) || '').toString();
      const originalLang = (formData.get('ORIGINAL_LANGUAGE') || '').toString();
      const langChanged = originalLang && currentLang && originalLang !== currentLang;
      const dismissMs = 1500;
      showAlert(statusBox, {
        message: successMsg,
        type: 'success',
        dismissMs,
        closable: false,
        className: 'py-2 px-3 mb-0',
      });
      setTimeout(() => {
        window.location.assign('/settings');
      }, dismissMs);
      return;
    } catch (err) {
      console.warn('Saving settings failed', err);
      showAlert(statusBox, {
        message: errorMsg,
        type: 'danger',
        dismissMs: 6000,
        closable: false,
        className: 'py-2 px-3 mb-0',
      });
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  function setTimezoneFromBrowser() {
    if (!tzInput) return;
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (tz) {
        tzInput.value = tz;
        if (tzInput instanceof HTMLSelectElement) {
          const option = Array.from(tzInput.options).find((opt) => opt.value === tz);
          if (option) {
            tzInput.value = tz;
          } else {
            // Add browser timezone to the list if it's not in the Top-50.
            const opt = document.createElement('option');
            opt.value = tz;
            opt.textContent = tz;
            tzInput.appendChild(opt);
            tzInput.value = tz;
          }
        }
      }
    } catch (err) {
      console.warn('Could not resolve browser timezone', err);
    }
  }

  function handleGeoError(err) {
    if (!showAlert) return;
    if (err && err.code === 1) {
      showAlert(statusBox, {
        message: geoDeniedMsg,
        type: 'warning',
        dismissMs: 6000,
        closable: false,
        className: 'py-2 px-3 mb-0',
      });
      return;
    }
    showAlert(statusBox, {
      message: geoErrorMsg,
      type: 'danger',
      dismissMs: 6000,
      closable: false,
      className: 'py-2 px-3 mb-0',
    });
  }

  function handleGeoSuccess(position) {
    if (!latInput || !lonInput) return;
    const { latitude, longitude } = position.coords || {};
    if (typeof latitude === 'number') latInput.value = latitude.toFixed(6);
    if (typeof longitude === 'number') lonInput.value = longitude.toFixed(6);
    setTimezoneFromBrowser();
    if (showAlert) {
      showAlert(statusBox, {
        message: geoSuccessMsg,
        type: 'success',
        dismissMs: 5000,
        closable: false,
        className: 'py-2 px-3 mb-0',
      });
    }
  }

  function handleGeoClick() {
    setTimezoneFromBrowser();
    if (!navigator.geolocation) {
      if (showAlert) {
        showAlert(statusBox, {
          message: geoUnsupportedMsg,
          type: 'warning',
          dismissMs: 6000,
          closable: false,
          className: 'py-2 px-3 mb-0',
        });
      }
      return;
    }
    if (geoBtn) geoBtn.disabled = true;
    navigator.geolocation.getCurrentPosition(handleGeoSuccess, handleGeoError, {
      enableHighAccuracy: true,
      timeout: 15000,
      maximumAge: 300000,
    });
    setTimeout(() => {
      if (geoBtn) geoBtn.disabled = false;
    }, 2000);
  }

  function clearDateRange(event) {
    if (event) event.preventDefault();
    if (dateFromInput) {
      dateFromInput.value = '';
      dateFromInput.dispatchEvent(new Event('input', { bubbles: true }));
      dateFromInput.dispatchEvent(new Event('change', { bubbles: true }));
    }
    if (dateToInput) {
      dateToInput.value = '';
      dateToInput.dispatchEvent(new Event('input', { bubbles: true }));
      dateToInput.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }

  form.addEventListener('submit', handleSubmit);
  if (geoBtn && latInput && lonInput) {
    geoBtn.addEventListener('click', handleGeoClick);
  }
  if (dateFromInput && dateToInput) {
    const clearValidity = () => validateDateRange(false);
    dateFromInput.addEventListener('input', clearValidity);
    dateToInput.addEventListener('input', clearValidity);
  }
  const liveValidate = () => validateForm(false);
  if (camUrlInput) camUrlInput.addEventListener('input', liveValidate);
  if (intervalInput) intervalInput.addEventListener('input', liveValidate);
  if (authTypeInput) authTypeInput.addEventListener('change', liveValidate);
  if (usernameInput) usernameInput.addEventListener('input', liveValidate);
  if (passwordInput) passwordInput.addEventListener('input', liveValidate);
  if (useAstralInput) useAstralInput.addEventListener('change', liveValidate);
  if (latInput) latInput.addEventListener('input', liveValidate);
  if (lonInput) lonInput.addEventListener('input', liveValidate);
  if (clearDateBtn && (dateFromInput || dateToInput)) {
    clearDateBtn.addEventListener('click', clearDateRange);
  }
  showSavedFromQuery();
})();


