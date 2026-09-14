import { describe, it, expect, beforeEach, afterEach, beforeAll, vi } from 'vitest';

type FetchResult = { ok: boolean; json: () => Promise<{ url: string; called: boolean }> };

describe('static/js/query-optimizer.js', () => {
  let optimizer: any;

  const fetchMock = vi.fn();

  beforeAll(async () => {
    await import('../../static/js/query-optimizer.js');
    optimizer = (window as any).queryOptimizer;
  });

  beforeEach(() => {
    optimizer.clearCache();
    optimizer.cacheTimeout = 60000;
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (url: string): Promise<FetchResult> => {
      return {
        ok: true,
        json: async () => ({ url, called: true })
      };
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('installs a singleton on window', () => {
    expect(optimizer).toBeTruthy();
  });

  it('builds a stable cache key from url and options', () => {
    expect(optimizer.getCacheKey('/api/x', { a: 1 })).toBe('/api/x_{"a":1}');
    expect(optimizer.getCacheKey('/api/x', { a: 1 })).toBe(
      optimizer.getCacheKey('/api/x', { a: 1 })
    );
  });

  it('fetches on first call and returns cached data on the second', async () => {
    const first = await optimizer.fetchWithCache('/api/orders', { method: 'GET' });
    const second = await optimizer.fetchWithCache('/api/orders', { method: 'GET' });

    expect(first).toEqual({ url: '/api/orders', called: true });
    expect(second).toEqual(first);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('treats different options as different cache entries', async () => {
    await optimizer.fetchWithCache('/api/orders', { page: 1 });
    await optimizer.fetchWithCache('/api/orders', { page: 2 });

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('refetches after the cache timeout has passed', async () => {
    optimizer.cacheTimeout = 0;

    await optimizer.fetchWithCache('/api/stale', {});
    await optimizer.fetchWithCache('/api/stale', {});

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('invalidates cache entries matching a pattern', async () => {
    await optimizer.fetchWithCache('/api/orders/list', {});
    await optimizer.fetchWithCache('/api/customers/list', {});

    optimizer.invalidateCache('/api/orders');

    await optimizer.fetchWithCache('/api/orders/list', {});
    await optimizer.fetchWithCache('/api/customers/list', {});

    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('clearCache forces a refetch of every url', async () => {
    await optimizer.fetchWithCache('/api/a', {});
    optimizer.clearCache();
    await optimizer.fetchWithCache('/api/a', {});

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('reports API timing to perfMonitor on cache miss', async () => {
    const measureAPICall = vi.fn();
    (window as any).perfMonitor = { measureAPICall };

    await optimizer.fetchWithCache('/api/timed', {});

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(measureAPICall).toHaveBeenCalledTimes(1);
    expect(measureAPICall.mock.calls[0][0]).toBe('/api/timed');
    expect(typeof measureAPICall.mock.calls[0][1]).toBe('number');
    delete (window as any).perfMonitor;
  });
});