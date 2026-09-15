import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

describe('static/js/dark-mode.js (extra)', () => {
  let originalMatchMedia: any;

  beforeEach(() => {
    originalMatchMedia = (window as any).matchMedia;
    localStorage.clear();
    document.body.innerHTML = '';
    document.body.classList.remove('dark-mode');
    vi.resetModules();
  });

  afterEach(() => {
    (window as any).matchMedia = originalMatchMedia;
    localStorage.clear();
    document.body.innerHTML = '';
    document.body.classList.remove('dark-mode');
  });

  function lastToggle(): HTMLButtonElement | null {
    const buttons = Array.from(document.querySelectorAll('.theme-toggle'));
    return (buttons[buttons.length - 1] as HTMLButtonElement) ?? null;
  }

  function stubMatchMedia(matches: boolean, listeners: Record<string, (e: any) => void>) {
    (window as any).matchMedia = () => ({
      matches,
      addEventListener: (ev: string, cb: (e: any) => void) => {
        listeners[ev] = cb;
      },
      removeEventListener: () => {}
    });
  }

  it('defaults to the light theme when nothing is saved', async () => {
    stubMatchMedia(false, {});
    expect(localStorage.getItem('theme')).toBeNull();

    await import('../../static/js/dark-mode.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    expect(document.body.classList.contains('dark-mode')).toBe(false);
    const button = lastToggle();
    expect(button).toBeTruthy();
    expect(button!.innerHTML).toBe('🌙');
    expect(button!.title).toBe('تبديل الوضع الليلي');
    expect(button!.className).toBe('theme-toggle');
  });

  it('shows the sun icon when dark mode is active on load', async () => {
    stubMatchMedia(false, {});
    localStorage.setItem('theme', 'dark');

    await import('../../static/js/dark-mode.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    expect(document.body.classList.contains('dark-mode')).toBe(true);
    expect(lastToggle()).toBeTruthy();
    expect(lastToggle()!.innerHTML).toBe('☀️');
  });

  it('ignores OS theme changes when the saved theme is light', async () => {
    const listeners: Record<string, (e: any) => void> = {};
    stubMatchMedia(false, listeners);
    localStorage.setItem('theme', 'light');

    await import('../../static/js/dark-mode.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    expect(document.body.classList.contains('dark-mode')).toBe(false);
    listeners['change']({ matches: true });

    expect(document.body.classList.contains('dark-mode')).toBe(false);
    expect(localStorage.getItem('theme')).toBe('light');
    expect(lastToggle()!.innerHTML).toBe('🌙');
  });

  it('ignores OS theme changes when the saved theme is dark', async () => {
    const listeners: Record<string, (e: any) => void> = {};
    stubMatchMedia(true, listeners);
    localStorage.setItem('theme', 'dark');

    await import('../../static/js/dark-mode.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    expect(document.body.classList.contains('dark-mode')).toBe(true);
    listeners['change']({ matches: false });

    expect(document.body.classList.contains('dark-mode')).toBe(true);
    expect(localStorage.getItem('theme')).toBe('dark');
    expect(lastToggle()!.innerHTML).toBe('☀️');
  });

  it('toggle button flips its icon together with the theme', async () => {
    stubMatchMedia(false, {});

    await import('../../static/js/dark-mode.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));

    const button = lastToggle() as HTMLButtonElement;
    expect(button.innerHTML).toBe('🌙');
    button.click();
    expect(document.body.classList.contains('dark-mode')).toBe(true);
    expect(button.innerHTML).toBe('☀️');
    expect(localStorage.getItem('theme')).toBe('dark');
    button.click();
    expect(document.body.classList.contains('dark-mode')).toBe(false);
    expect(button.innerHTML).toBe('🌙');
    expect(localStorage.getItem('theme')).toBe('light');
  });
});
