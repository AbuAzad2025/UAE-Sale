/**
 * Error Reporter — captures every browser-side fault and files it
 * with the server error journal (POST /api/client-errors).
 *
 * Dependency-free on purpose: it must work even when the rest of the
 * frontend is broken. Transport functions are injectable so the module
 * is fully unit-testable.
 */
(function () {
  'use strict';

  var ENDPOINT = '/api/client-errors';
  var MAX_MESSAGE = 2000;
  var MAX_STACK = 8000;
  var MAX_PAGE = 500;
  var INSTALLED_FLAG = '__azadErrorReporterInstalled';

  function trunc(value, limit) {
    var text = value === undefined || value === null ? '' : String(value);
    if (text.length > limit) {
      return text.slice(0, limit) + '…[truncated]';
    }
    return text;
  }

  function currentPage() {
    try {
      return window.location ? window.location.href : '';
    } catch (e) {
      return '';
    }
  }

  function currentAgent() {
    try {
      return window.navigator ? window.navigator.userAgent : '';
    } catch (e) {
      return '';
    }
  }

  /**
   * Build the report payload. Pure function (no I/O).
   */
  function buildPayload(options) {
    var opts = options || {};
    return {
      message: trunc(opts.message || 'Unknown browser error', MAX_MESSAGE),
      stack: opts.stack ? trunc(opts.stack, MAX_STACK) : null,
      page: trunc(opts.page || currentPage(), MAX_PAGE),
      userAgent: trunc(opts.agent || currentAgent(), MAX_PAGE),
      kind: opts.kind === 'unhandledrejection' ? 'unhandledrejection' : 'onerror'
    };
  }

  function defaultBeacon(url, body) {
    try {
      if (typeof window.navigator !== 'undefined' &&
          typeof window.navigator.sendBeacon === 'function') {
        var blob = new Blob([body], { type: 'application/json' });
        return window.navigator.sendBeacon(url, blob);
      }
    } catch (e) {
      return false;
    }
    return false;
  }

  function defaultFetch(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body,
      keepalive: true,
      credentials: 'same-origin'
    }).catch(function () {
      return null;
    });
  }

  /**
   * Send one report. Beacon first (survives page unload), fetch fallback.
   * Never throws; never breaks the page it reports from.
   */
  function sendReport(payload, transports) {
    var t = transports || {};
    var beacon = t.beacon || defaultBeacon;
    var fetchFn = t.fetchFn || defaultFetch;
    var body;
    try {
      body = JSON.stringify(payload);
    } catch (e) {
      return Promise.resolve(false);
    }
    var sent = false;
    try {
      sent = !!beacon(ENDPOINT, body);
    } catch (e) {
      sent = false;
    }
    if (sent) {
      return Promise.resolve(true);
    }
    try {
      return Promise.resolve()
        .then(function () {
          return fetchFn(ENDPOINT, body);
        })
        .then(
          function () {
            return true;
          },
          function () {
            return false;
          }
        );
    } catch (e) {
      return Promise.resolve(false);
    }
  }

  /**
   * Wire window.onerror + unhandledrejection. Chains any previously
   * installed handler (e.g. the toast-only one) so nothing is lost.
   * Safe to call repeatedly: reinstalls cleanly instead of stacking.
   */
  function install(transports) {
    if (window[INSTALLED_FLAG]) {
      uninstall();
    }
    var previousOnError =
      typeof window.onerror === 'function' ? window.onerror : null;

    window.onerror = function (msg, src, line, col, err) {
      try {
        sendReport(buildPayload({
          message: msg,
          stack: err && err.stack ? err.stack : null,
          kind: 'onerror'
        }), transports);
      } catch (e) {
        /* reporting must never break the page */
      }
      if (previousOnError) {
        try {
          return previousOnError(msg, src, line, col, err);
        } catch (e2) {
          return false;
        }
      }
      return false;
    };

    var onRejection = function (event) {
      var reason = event && event.reason;
      var message = 'Unhandled rejection';
      var stack = null;
      if (reason) {
        message = reason.message ? String(reason.message) : String(reason);
        stack = reason.stack ? String(reason.stack) : null;
      }
      try {
        sendReport(buildPayload({
          message: message,
          stack: stack,
          kind: 'unhandledrejection'
        }), transports);
      } catch (e) {
        /* reporting must never break the page */
      }
    };

    window.addEventListener('unhandledrejection', onRejection);
    window[INSTALLED_FLAG] = {
      onerror: window.onerror,
      rejection: onRejection,
      previousOnerror: previousOnError
    };
    return true;
  }

  function uninstall() {
    var current = window[INSTALLED_FLAG];
    if (!current) {
      return;
    }
    try {
      window.removeEventListener('unhandledrejection', current.rejection);
    } catch (e) {
      /* ignore */
    }
    window.onerror = current.previousOnerror || null;
    window[INSTALLED_FLAG] = null;
  }

  window.ErrorReporter = {
    ENDPOINT: ENDPOINT,
    buildPayload: buildPayload,
    sendReport: sendReport,
    install: install,
    uninstall: uninstall
  };

  // Auto-install (page context only — harmless under test runners).
  try {
    if (typeof document !== 'undefined' && !window[INSTALLED_FLAG]) {
      if (document.readyState !== 'loading') {
        install();
      } else {
        document.addEventListener('DOMContentLoaded', function () {
          install();
        });
      }
    }
  } catch (e) {
    /* never break page load */
  }
})();
