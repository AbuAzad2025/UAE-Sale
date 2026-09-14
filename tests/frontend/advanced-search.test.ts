import { describe, it, expect, beforeEach, afterEach, beforeAll, vi } from 'vitest';

function queryParam(url: string, param: string): string | null {
  const query = url.includes('?') ? url.split('?')[1] : '';
  return new URLSearchParams(query).get(param);
}

describe('static/js/advanced-search.js', () => {
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
        json: async () => ({ query: queryParam(url, 'q'), success: true })
      };
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('exposes the AdvancedSearch class on window', () => {
    expect(typeof AdvancedSearch).toBe('function');
  });

  it('does not search when the query is shorter than minLength (default 2)', async () => {
    const onResult = vi.fn();
    const searcher = new AdvancedSearch({ onResult });

    searcher.search('a');
    await vi.advanceTimersByTimeAsync(500);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(onResult).not.toHaveBeenCalled();
  });

  it('searches after the debounce delay', async () => {
    const onResult = vi.fn();
    const searcher = new AdvancedSearch({ onResult, debounceDelay: 300 });

    searcher.search('invoice');
    await vi.advanceTimersByTimeAsync(299);
    expect(fetchMock).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(onResult).toHaveBeenCalledWith({ query: 'invoice', success: true });
  });

  it('debounces rapid consecutive searches to the last query', async () => {
    const onResult = vi.fn();
    const searcher = new AdvancedSearch({ onResult, debounceDelay: 300 });

    searcher.search('in');
    searcher.search('inv');
    searcher.search('invoice');
    await vi.advanceTimersByTimeAsync(300);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(onResult).toHaveBeenCalledTimes(1);
    expect(onResult).toHaveBeenCalledWith({ query: 'invoice', success: true });
  });

  it('clear() cancels a pending debounced search', async () => {
    const onResult = vi.fn();
    const searcher = new AdvancedSearch({ onResult, debounceDelay: 300 });

    searcher.search('invoice');
    searcher.clear();
    await vi.advanceTimersByTimeAsync(400);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(onResult).not.toHaveBeenCalled();
  });

  it('reports fetch failures through onResult', async () => {
    fetchMock.mockRejectedValue(new Error('Network down'));
    const onResult = vi.fn();
    const searcher = new AdvancedSearch({ onResult, debounceDelay: 0 });

    await searcher.executeSearch('invoice');

    expect(onResult).toHaveBeenCalledWith({ success: false, error: 'Network down' });
  });

  it('reports API timing to perfMonitor when available', async () => {
    const measureAPICall = vi.fn();
    (window as any).perfMonitor = { measureAPICall };
    const onResult = vi.fn();
    const searcher = new AdvancedSearch({ onResult });

    await searcher.executeSearch('invoice');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(measureAPICall).toHaveBeenCalledTimes(1);
    expect(measureAPICall.mock.calls[0][0]).toBe('/api/v2/search');
    expect(typeof measureAPICall.mock.calls[0][1]).toBe('number');
    expect(onResult).toHaveBeenCalledTimes(1);
    delete (window as any).perfMonitor;
  });
});