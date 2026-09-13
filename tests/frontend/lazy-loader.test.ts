import { describe, it, expect, beforeEach, vi } from 'vitest';

describe('static/js/lazy-loader.js', () => {
  beforeEach(() => {
    vi.resetModules();
    (window as any).lazyLoader = undefined;

    const observed: HTMLElement[] = [];
    const instances: any[] = [];

    class FakeIntersectionObserver {
      callback: any;
      constructor(cb: any) {
        this.callback = cb;
        instances.push(this);
      }
      observe(el: HTMLElement) {
        observed.push(el);
      }
      unobserve() {}
      disconnect() {}
    }

    (window as any).__lazyLoaderTest = { observed, instances };
    (window as any).IntersectionObserver = FakeIntersectionObserver;
  });

  it('exposes lazyLoader on window', async () => {
    await import('../../static/js/lazy-loader.js');
    expect((window as any).lazyLoader).toBeTruthy();
  });

  it('observes images that have a data-src attribute', async () => {
    document.body.innerHTML = '<img data-src="/assets/logo.png" alt="logo">';

    await import('../../static/js/lazy-loader.js');
    const { observed } = (window as any).__lazyLoaderTest;

    expect(observed.length).toBe(1);
    expect(observed[0]).toBe(document.querySelector('img'));
  });

  it('does not observe images that already have a src', async () => {
    document.body.innerHTML = '<img src="/assets/ready.png" alt="ready">';

    await import('../../static/js/lazy-loader.js');
    const { observed } = (window as any).__lazyLoaderTest;

    expect(observed.length).toBe(0);
  });

  it('populates img.src when the observer reports the image is intersecting', async () => {
    document.body.innerHTML = '<img data-src="/assets/lazy.png" alt="lazy">';

    await import('../../static/js/lazy-loader.js');

    const img = document.querySelector('img') as HTMLImageElement;
    const { instances } = (window as any).__lazyLoaderTest;
    instances[0].callback([{ isIntersecting: true, target: img }]);

    expect(img.getAttribute('src')).toBe('/assets/lazy.png');
    expect(img.hasAttribute('data-src')).toBe(false);
  });

  it('leaves data-src untouched for entries that are not intersecting', async () => {
    document.body.innerHTML = '<img data-src="/assets/nope.png" alt="nope">';

    await import('../../static/js/lazy-loader.js');

    const img = document.querySelector('img') as HTMLImageElement;
    const { instances } = (window as any).__lazyLoaderTest;
    instances[0].callback([{ isIntersecting: false, target: img }]);

    expect(img.getAttribute('src')).toBeNull();
    expect(img.getAttribute('data-src')).toBe('/assets/nope.png');
  });
});