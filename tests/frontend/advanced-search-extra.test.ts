import { describe, it, expect, beforeEach, afterEach, beforeAll, vi } from 'vitest';

describe('static/js/advanced-search.js (extra)', () => {
  let AdvancedSearch: any;

  const fetchMock = vi.fn();

  beforeAll(async () => {
    await import('../../static/js/advanced-search.js');
    AdvancedSearch = (window as any).AdvancedSearch;
  });

  beforeEach(() => {
    vi.useFakeTimers();
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (url: string) => {
      return {
        ok: true,
        json: async () => ({ url, success: true })
      };
    });
    vi.stubGlobal('fetch', fetchMock);
    delete (window as any).perfMonitor;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    delete (window as any).perfMonitor;
  });

  it('applies default options when none are given', () => {
    const searcher = new AdvancedSearch();
    expect(searcher.endpoint).toBe('/api/v2/search');
    expect(searcher.debounceDelay).toBe(300);
    expect(searcher.minLength).toBe(2);
    expect(typeof searcher.onResult).toBe('function');
  });

  it('default onResult is a safe no-op for debounced searches', async () => {
    const searcher = new AdvancedSearch({ debounceDelay: 10 });
    searcher.search('hello');
    await vi.advanceTimersByTimeAsync(50);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('executeSearch works with the default onResult', async () => {
    const searcher = new AdvancedSearch();
    await expect(searcher.executeSearch('hello')).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url: string = fetchMock.mock.calls[0][0];
    expect(url).toContain('/api/v2/search');
    expect(url).toContain('q=hello');
  });

  it('sends filters as query params to a custom endpoint', async () => {
    const onResult = vi.fn();
    const searcher = new AdvancedSearch({ endpoint: '/api/custom', onResult, debounceDelay: 100 });

    searcher.search('laptop', { category: 'electronics', inStock: 'true' });
    await vi.advanceTimersByTimeAsync(100);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url: string = fetchMock.mock.calls[0][0];
    expect(url.startsWith('/api/custom?')).toBe(true);
    const params = new URLSearchParams(url.split('?')[1]);
    expect(params.get('q')).toBe('laptop');
    expect(params.get('category')).toBe('electronics');
    expect(params.get('inStock')).toBe('true');
    expect(onResult).toHaveBeenCalledTimes(1);
  });

  it('honours a custom minLength', async () => {
    const onResult = vi.fn();
    const searcher = new AdvancedSearch({ onResult, debounceDelay: 50, minLength: 5 });

    searcher.search('abcd');
    await vi.advanceTimersByTimeAsync(200);
    expect(fetchMock).not.toHaveBeenCalled();

    searcher.search('abcde');
    await vi.advanceTimersByTimeAsync(200);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('queries without perfMonitor when it is absent', async () => {
    const onResult = vi.fn();
    const searcher = new AdvancedSearch({ onResult });
    await searcher.executeSearch('quiet');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(onResult).toHaveBeenCalledTimes(1);
    expect((window as any).perfMonitor).toBeUndefined();
  });
});
