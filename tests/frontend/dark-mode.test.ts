import { describe, it, expect, beforeEach, vi } from 'vitest';

describe('static/js/dark-mode.js', () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = '';
    document.body.classList.remove('dark-mode');
  });

  it('enables dark mode when the saved theme is dark', async () => {
    localStorage.setItem('theme', 'dark');

    await import('../../static/js/dark-mode.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    expect(document.body.classList.contains('dark-mode')).toBe(true);
    expect(document.querySelector('.theme-toggle')).toBeTruthy();
  });

  it('stays light when the saved theme is light', async () => {
    localStorage.setItem('theme', 'light');

    await import('../../static/js/dark-mode.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    expect(document.body.classList.contains('dark-mode')).toBe(false);
  });

  it('toggles the theme and persists it on click', async () => {
    localStorage.setItem('theme', 'light');

    await import('../../static/js/dark-mode.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    const button = document.querySelector('.theme-toggle') as HTMLButtonElement;
    await new Promise((r) => setTimeout(r, 0));
    button.click();

    expect(document.body.classList.contains('dark-mode')).toBe(true);
    expect(localStorage.getItem('theme')).toBe('dark');

    button.click();

    expect(document.body.classList.contains('dark-mode')).toBe(false);
    expect(localStorage.getItem('theme')).toBe('light');
  });

  it('follows the OS preference when theme is auto and dark is preferred', async () => {
    (window as any).__setPrefersDark(true);
    localStorage.setItem('theme', 'auto');

    await import('../../static/js/dark-mode.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    expect(document.body.classList.contains('dark-mode')).toBe(true);
    (window as any).__setPrefersDark(false);
  });

  it('stays light when theme is auto and OS prefers light', async () => {
    (window as any).__setPrefersDark(false);
    localStorage.setItem('theme', 'auto');

    await import('../../static/js/dark-mode.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    expect(document.body.classList.contains('dark-mode')).toBe(false);
  });

  it('reacts to OS theme changes while theme is auto', async () => {
    vi.resetModules();
    const listeners: Record<string, (e: any) => void> = {};
    (window as any).matchMedia = () => ({
      matches: false,
      addEventListener: (ev: string, cb: (e: any) => void) => {
        listeners[ev] = cb;
      },
      removeEventListener: () => {}
    });
    localStorage.clear();
    document.body.innerHTML = '';
    document.body.classList.remove('dark-mode');
    localStorage.setItem('theme', 'auto');

    await import('../../static/js/dark-mode.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    expect(document.body.classList.contains('dark-mode')).toBe(false);
    listeners['change']({ matches: true });
    expect(document.body.classList.contains('dark-mode')).toBe(true);
    listeners['change']({ matches: false });
    expect(document.body.classList.contains('dark-mode')).toBe(false);
  });

  it('applies dark mode on load when OS prefers dark and theme is auto', async () => {
    vi.resetModules();
    (window as any).matchMedia = () => ({
      matches: true,
      addEventListener: () => {},
      removeEventListener: () => {}
    });
    localStorage.clear();
    document.body.innerHTML = '';
    document.body.classList.remove('dark-mode');
    localStorage.setItem('theme', 'auto');

    await import('../../static/js/dark-mode.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    expect(document.body.classList.contains('dark-mode')).toBe(true);
  });
});