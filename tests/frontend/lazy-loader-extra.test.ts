import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

describe('static/js/lazy-loader.js (extra)', () => {
  let observed: HTMLElement[];
  let instances: any[];
  let unobserved: HTMLElement[];

  beforeEach(() => {
    vi.resetModules();
    (window as any).lazyLoader = undefined;
    document.body.innerHTML = '';
    observed = [];
    instances = [];
    unobserved = [];
    const obs = observed;
    const inst = instances;
    const un = unobserved;

    class FakeIntersectionObserver {
      callback: any;
      constructor(cb: any) {
        this.callback = cb;
        inst.push(this);
      }
      observe(el: HTMLElement) {
        obs.push(el);
      }
      unobserve(el: HTMLElement) {
        un.push(el);
      }
      disconnect() {}
    }

    (window as any).IntersectionObserver = FakeIntersectionObserver;
  });

  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('calls unobserve after a lazy image loads', async () => {
    document.body.innerHTML = '<img data-src="/assets/a.png" alt="a">';

    await import('../../static/js/lazy-loader.js');

    const img = document.querySelector('img') as HTMLImageElement;
    instances[0].callback([{ isIntersecting: true, target: img }]);

    expect(img.getAttribute('src')).toBe('/assets/a.png');
    expect(unobserved.length).toBe(1);
    expect(unobserved[0]).toBe(img);
  });

  it('skips images without data-src even when intersecting', async () => {
    document.body.innerHTML = '<img src="/assets/ready.png" alt="ready">';

    await import('../../static/js/lazy-loader.js');

    const img = document.querySelector('img') as HTMLImageElement;
    instances[0].callback([{ isIntersecting: true, target: img }]);

    expect(img.getAttribute('src')).toBe('/assets/ready.png');
    expect(img.hasAttribute('data-src')).toBe(false);
    expect(unobserved.length).toBe(0);
  });

  it('does not load when the target lost data-src before the callback', async () => {
    document.body.innerHTML = '<img data-src="/assets/b.png" alt="b">';

    await import('../../static/js/lazy-loader.js');

    const img = document.querySelector('img') as HTMLImageElement;
    img.removeAttribute('data-src');
    instances[0].callback([{ isIntersecting: true, target: img }]);

    expect(img.getAttribute('src')).toBeNull();
    expect(unobserved.length).toBe(0);
  });

  it('initializes cleanly when IntersectionObserver is unavailable', async () => {
    delete (window as any).IntersectionObserver;
    document.body.innerHTML = '<img data-src="/assets/c.png" alt="c">';

    await import('../../static/js/lazy-loader.js');

    const loader = (window as any).lazyLoader;
    expect(loader).toBeTruthy();
    expect(loader.observers.size).toBe(0);
    expect(() => loader.observeImages()).not.toThrow();
    expect(document.querySelector('img')?.getAttribute('data-src')).toBe('/assets/c.png');
    expect(document.querySelector('img')?.getAttribute('src')).toBeNull();
  });

  it('loadModule returns a rejected promise for a missing module', async () => {
    await import('../../static/js/lazy-loader.js');

    const loader = (window as any).lazyLoader;
    expect(typeof loader.loadModule).toBe('function');
    const result = loader.loadModule('does-not-exist-xyz');
    expect(result && typeof result.then).toBe('function');
    const outcome = await result.then(
      () => 'resolved',
      () => 'rejected'
    );
    expect(outcome).toBe('rejected');
  });
});
