import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';

describe('static/js/error-reporter.js', () => {
  beforeAll(async () => {
    await import('../../static/js/error-reporter.js');
  });

  afterEach(() => {
    (window as any).ErrorReporter?.uninstall();
    vi.restoreAllMocks();
  });

  it('exposes the reporter API on window', () => {
    const reporter = (window as any).ErrorReporter;
    expect(typeof reporter.buildPayload).toBe('function');
    expect(typeof reporter.sendReport).toBe('function');
    expect(typeof reporter.install).toBe('function');
    expect(reporter.ENDPOINT).toBe('/api/client-errors');
  });

  it('buildPayload truncates long fields', () => {
    const payload = (window as any).ErrorReporter.buildPayload({
      message: 'A'.repeat(5000),
      stack: 'B'.repeat(9000),
      page: '/sales/create',
      kind: 'onerror'
    });
    expect(payload.message.length).toBeLessThanOrEqual(2012);
    expect(payload.message.endsWith('[truncated]')).toBe(true);
    expect(payload.stack.length).toBeLessThanOrEqual(8012);
    expect(payload.page).toBe('/sales/create');
    expect(payload.kind).toBe('onerror');
  });

  it('buildPayload maps unhandledrejection kind and defaults stack to null', () => {
    const payload = (window as any).ErrorReporter.buildPayload({
      message: 'boom',
      kind: 'unhandledrejection'
    });
    expect(payload.kind).toBe('unhandledrejection');
    expect(payload.stack).toBeNull();
  });

  it('sendReport prefers beacon and skips fetch on success', async () => {
    const beacon = vi.fn().mockReturnValue(true);
    const fetchFn = vi.fn();
    const ok = await (window as any).ErrorReporter.sendReport(
      { message: 'm' },
      { beacon, fetchFn }
    );
    expect(ok).toBe(true);
    expect(beacon).toHaveBeenCalledTimes(1);
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it('sendReport falls back to fetch with JSON body', async () => {
    const beacon = vi.fn().mockReturnValue(false);
    const fetchFn = vi.fn().mockResolvedValue({ ok: true });
    const ok = await (window as any).ErrorReporter.sendReport(
      { message: 'm', kind: 'onerror' },
      { beacon, fetchFn }
    );
    expect(ok).toBe(true);
    expect(fetchFn).toHaveBeenCalledTimes(1);
    expect(fetchFn.mock.calls[0][0]).toBe('/api/client-errors');
    expect(JSON.parse(fetchFn.mock.calls[0][1]).message).toBe('m');
  });

  it('sendReport never rejects on transport failure', async () => {
    const fetchFn = vi.fn().mockRejectedValue(new Error('down'));
    const ok = await (window as any).ErrorReporter.sendReport(
      { message: 'm' },
      { beacon: () => false, fetchFn }
    );
    expect(ok).toBe(false);
  });

  it('install chains the previous onerror handler', async () => {
    (window as any).ErrorReporter.uninstall();
    const prev = vi.fn();
    (window as any).onerror = prev;
    const fetchFn = vi.fn().mockResolvedValue({ ok: true });
    (window as any).ErrorReporter.install({ beacon: () => false, fetchFn });

    const err = new Error('boom');
    (window as any).onerror('boom', 'http://t/x', 10, 20, err);
    await new Promise((r) => setTimeout(r, 0));

    expect(fetchFn).toHaveBeenCalledTimes(1);
    expect(prev).toHaveBeenCalledWith('boom', 'http://t/x', 10, 20, err);
    (window as any).onerror = null;
  });

  it('install captures unhandledrejection events', async () => {
    (window as any).ErrorReporter.uninstall();
    const fetchFn = vi.fn().mockResolvedValue({ ok: true });
    (window as any).ErrorReporter.install({ beacon: () => false, fetchFn });

    window.dispatchEvent(new Event('unhandledrejection'));
    await new Promise((r) => setTimeout(r, 0));

    expect(fetchFn).toHaveBeenCalledTimes(1);
    const sent = JSON.parse(fetchFn.mock.calls[0][1]);
    expect(sent.kind).toBe('unhandledrejection');
  });

  it('reinstall does not stack duplicate reporters', async () => {
    (window as any).ErrorReporter.uninstall();
    const fetchFn = vi.fn().mockResolvedValue({ ok: true });
    const transports = { beacon: () => false, fetchFn };
    (window as any).ErrorReporter.install(transports);
    (window as any).ErrorReporter.install(transports);

    (window as any).onerror('m', 'u', 1, 2, null);
    await new Promise((r) => setTimeout(r, 0));

    expect(fetchFn).toHaveBeenCalledTimes(1);
  });

  it('uses page and agent defaults from the browser', () => {
    const payload = (window as any).ErrorReporter.buildPayload({ message: 'm' });
    expect(typeof payload.page).toBe('string');
    expect(typeof payload.userAgent).toBe('string');
  });

  it('falls back to global fetch when no transports given', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal('fetch', fetchMock);
    const ok = await (window as any).ErrorReporter.sendReport({ message: 'm' });
    expect(ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });

  it('uses navigator.sendBeacon when available', async () => {
    const sendBeacon = vi.fn().mockReturnValue(true);
    (window as any).navigator.sendBeacon = sendBeacon;
    try {
      const ok = await (window as any).ErrorReporter.sendReport({ message: 'm' });
      expect(ok).toBe(true);
      expect(sendBeacon).toHaveBeenCalledTimes(1);
    } finally {
      delete (window as any).navigator.sendBeacon;
    }
  });
});