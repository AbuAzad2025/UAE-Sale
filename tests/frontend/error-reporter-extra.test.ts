import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';

const FLAG = '__azadErrorReporterInstalled';

describe('static/js/error-reporter.js (extra)', () => {
  beforeAll(async () => {
    await import('../../static/js/error-reporter.js');
  });

  afterEach(() => {
    (window as any).ErrorReporter?.uninstall();
    (window as any).onerror = null;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  function reporter() {
    return (window as any).ErrorReporter;
  }

  const tick = () => new Promise((r) => setTimeout(r, 0));

  it('buildPayload falls back to defaults with no options', () => {
    const p = reporter().buildPayload();
    expect(p.message).toBe('Unknown browser error');
    expect(p.stack).toBeNull();
    expect(p.kind).toBe('onerror');
    expect(typeof p.page).toBe('string');
    expect(typeof p.userAgent).toBe('string');
  });

  it('buildPayload normalises an unknown kind to onerror', () => {
    const p = reporter().buildPayload({ message: 'x', kind: 'boom' });
    expect(p.kind).toBe('onerror');
  });

  it('buildPayload truncates an over-long page', () => {
    const p = reporter().buildPayload({ message: 'm', page: 'p'.repeat(1000) });
    expect(p.page.endsWith('…[truncated]')).toBe(true);
    expect(p.page.length).toBeLessThanOrEqual(512);
  });

  it('buildPayload reads the live page URL and user agent', () => {
    const p = reporter().buildPayload({ message: 'm' });
    expect(p.page).toBe(window.location.href);
    expect(p.userAgent).toBe(window.navigator.userAgent);
  });

  function shadowWindowProp(name: 'location' | 'navigator', descriptor: PropertyDescriptor) {
    const existing = Object.getOwnPropertyDescriptor(window, name);
    Object.defineProperty(window, name, { ...descriptor, configurable: true });
    return () => {
      if (existing) {
        Object.defineProperty(window, name, existing);
      } else {
        delete (window as any)[name];
      }
    };
  }

  it('falls back to empty strings when browser fields are missing', () => {
    const restoreLocation = shadowWindowProp('location', { value: undefined, writable: true });
    const restoreNavigator = shadowWindowProp('navigator', { value: undefined, writable: true });
    try {
      const p = reporter().buildPayload({ message: 'm' });
      expect(p.page).toBe('');
      expect(p.userAgent).toBe('');
    } finally {
      restoreLocation();
      restoreNavigator();
    }
  });

  it('survives throwing browser getters', () => {
    const restoreLocation = shadowWindowProp('location', {
      get() {
        throw new Error('denied');
      }
    });
    const restoreNavigator = shadowWindowProp('navigator', {
      get() {
        throw new Error('denied');
      }
    });
    try {
      const p = reporter().buildPayload({ message: 'm' });
      expect(p.page).toBe('');
      expect(p.userAgent).toBe('');
    } finally {
      restoreLocation();
      restoreNavigator();
    }
  });

  it('sendReport resolves false for circular payloads without touching transports', async () => {
    const beacon = vi.fn();
    const fetchFn = vi.fn();
    const circular: any = { message: 'm' };
    circular.self = circular;
    const ok = await reporter().sendReport(circular, { beacon, fetchFn });
    expect(ok).toBe(false);
    expect(beacon).not.toHaveBeenCalled();
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it('sendReport survives a throwing beacon and uses fetch', async () => {
    const beacon = vi.fn(() => {
      throw new Error('beacon boom');
    });
    const fetchFn = vi.fn().mockResolvedValue({ ok: true });
    const ok = await reporter().sendReport({ message: 'm' }, { beacon, fetchFn });
    expect(ok).toBe(true);
    expect(beacon).toHaveBeenCalledTimes(1);
    expect(fetchFn).toHaveBeenCalledTimes(1);
    expect(fetchFn.mock.calls[0][0]).toBe('/api/client-errors');
  });

  it('sendReport resolves false when fetchFn throws synchronously', async () => {
    const fetchFn = vi.fn(() => {
      throw new Error('sync');
    });
    const ok = await reporter().sendReport({ message: 'm' }, { beacon: () => false, fetchFn });
    expect(ok).toBe(false);
  });

  it('sendReport resolves false when the promise chain cannot start', async () => {
    const spy = vi.spyOn(Promise, 'resolve').mockImplementationOnce(() => {
      throw new Error('no promise');
    });
    try {
      const fetchFn = vi.fn();
      const ok = await reporter().sendReport({ message: 'm' }, { beacon: () => false, fetchFn });
      expect(ok).toBe(false);
      expect(fetchFn).not.toHaveBeenCalled();
    } finally {
      spy.mockRestore();
    }
  });

  it('defaultBeacon failure still delivers via global fetch', async () => {
    const nav = (window as any).navigator;
    const hadBeacon = nav && 'sendBeacon' in nav;
    const origBeacon = nav?.sendBeacon;
    nav.sendBeacon = () => {
      throw new Error('nope');
    };
    try {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true });
      vi.stubGlobal('fetch', fetchMock);
      const ok = await reporter().sendReport({ message: 'm' });
      expect(ok).toBe(true);
      expect(fetchMock).toHaveBeenCalledTimes(1);
    } finally {
      if (!hadBeacon) {
        delete nav.sendBeacon;
      } else {
        nav.sendBeacon = origBeacon;
      }
    }
  });

  it('defaultFetch swallows a network failure and still resolves true', async () => {
    const nav = (window as any).navigator;
    const hadBeacon = nav && 'sendBeacon' in nav;
    const origBeacon = nav?.sendBeacon;
    if (nav) {
      delete nav.sendBeacon;
    }
    try {
      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('net down')));
      const ok = await reporter().sendReport({ message: 'm' });
      expect(ok).toBe(true);
    } finally {
      if (hadBeacon && nav) {
        nav.sendBeacon = origBeacon;
      }
    }
  });

  it('installed onerror returns false and still reports without a previous handler', async () => {
    reporter().uninstall();
    (window as any).onerror = null;
    const fetchFn = vi.fn().mockResolvedValue({ ok: true });
    reporter().install({ beacon: () => false, fetchFn });

    const err = new Error('plain');
    const ret = (window as any).onerror('m', 'u', 1, 2, err);
    await tick();

    expect(ret).toBe(false);
    expect(fetchFn).toHaveBeenCalledTimes(1);
    const sent = JSON.parse(fetchFn.mock.calls[0][1]);
    expect(sent.message).toBe('m');
    expect(sent.stack).toContain('plain');
    expect(sent.kind).toBe('onerror');
  });

  it('installed onerror returns false when the previous handler throws', async () => {
    reporter().uninstall();
    (window as any).onerror = () => {
      throw new Error('prev boom');
    };
    const fetchFn = vi.fn().mockResolvedValue({ ok: true });
    reporter().install({ beacon: () => false, fetchFn });

    const ret = (window as any).onerror('m', 'u', 1, 2, null);
    await tick();

    expect(ret).toBe(false);
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });

  it('captures Error objects from unhandledrejection with message and stack', async () => {
    reporter().uninstall();
    const fetchFn = vi.fn().mockResolvedValue({ ok: true });
    reporter().install({ beacon: () => false, fetchFn });

    const event = new Event('unhandledrejection') as any;
    event.reason = new Error('rej boom');
    window.dispatchEvent(event);
    await tick();

    expect(fetchFn).toHaveBeenCalledTimes(1);
    const sent = JSON.parse(fetchFn.mock.calls[0][1]);
    expect(sent.message).toBe('rej boom');
    expect(sent.stack).toContain('rej boom');
    expect(sent.kind).toBe('unhandledrejection');
  });

  it('captures string rejection reasons without a stack', async () => {
    reporter().uninstall();
    const fetchFn = vi.fn().mockResolvedValue({ ok: true });
    reporter().install({ beacon: () => false, fetchFn });

    const event = new Event('unhandledrejection') as any;
    event.reason = 'just a string';
    window.dispatchEvent(event);
    await tick();

    expect(fetchFn).toHaveBeenCalledTimes(1);
    const sent = JSON.parse(fetchFn.mock.calls[0][1]);
    expect(sent.message).toBe('just a string');
    expect(sent.stack).toBeNull();
    expect(sent.kind).toBe('unhandledrejection');
  });

  it('uninstall without a previous handler resets onerror to null', () => {
    reporter().uninstall();
    (window as any).onerror = null;
    reporter().install({ beacon: () => true, fetchFn: vi.fn() });
    expect(typeof (window as any).onerror).toBe('function');
    reporter().uninstall();
    expect((window as any).onerror).toBeNull();
    expect((window as any)[FLAG]).toBeFalsy();
  });

  it('auto-installs on import when the document is already loaded', async () => {
    reporter().uninstall();
    (window as any).onerror = null;
    vi.resetModules();
    await import('../../static/js/error-reporter.js');
    expect(typeof (window as any).onerror).toBe('function');
    expect((window as any)[FLAG]).toBeTruthy();
  });

  it('defers auto-install via DOMContentLoaded while the document is loading', async () => {
    const savedReporter = (window as any).ErrorReporter;
    const savedOnError = (window as any).onerror;
    const savedFlag = (window as any)[FLAG];
    try {
      savedReporter.uninstall();
      (window as any).onerror = null;
      const readyDesc =
        Object.getOwnPropertyDescriptor(document, 'readyState') ??
        Object.getOwnPropertyDescriptor(Object.getPrototypeOf(document), 'readyState');
      Object.defineProperty(document, 'readyState', { value: 'loading', configurable: true });
      try {
        vi.resetModules();
        await import('../../static/js/error-reporter.js');
        expect((window as any)[FLAG]).toBeFalsy();
        document.dispatchEvent(new Event('DOMContentLoaded'));
        expect((window as any)[FLAG]).toBeTruthy();
        expect(typeof (window as any).onerror).toBe('function');
      } finally {
        if (readyDesc && 'value' in readyDesc) {
          Object.defineProperty(document, 'readyState', { value: readyDesc.value, configurable: true });
        } else {
          delete (document as any).readyState;
        }
      }
    } finally {
      (window as any).ErrorReporter.uninstall();
      (window as any).ErrorReporter = savedReporter;
      (window as any).onerror = savedOnError;
      (window as any)[FLAG] = savedFlag;
    }
  });

  it('fresh import skips auto-install while a reporter is already installed', async () => {
    const savedReporter = (window as any).ErrorReporter;
    const savedFlag = (window as any)[FLAG];
    try {
      savedReporter.uninstall();
      savedReporter.install({ beacon: () => true, fetchFn: vi.fn() });
      const installedOnError = (window as any).onerror;
      expect((window as any)[FLAG]).toBeTruthy();
      vi.resetModules();
      await import('../../static/js/error-reporter.js');
      expect((window as any).onerror).toBe(installedOnError);
      expect((window as any)[FLAG]).toBeTruthy();
    } finally {
      (window as any).ErrorReporter.uninstall();
      (window as any).ErrorReporter = savedReporter;
      (window as any)[FLAG] = savedFlag;
    }
  });
});
