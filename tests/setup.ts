export {};

if (typeof window !== 'undefined') {
  let prefersDark = false;

  Object.defineProperty(window, '__setPrefersDark', {
    value: (dark: boolean) => {
      prefersDark = dark;
    },
    configurable: true
  });

  if (!window.matchMedia) {
    window.matchMedia = (query: string): MediaQueryList => ({
      matches: prefersDark,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false
    }) as unknown as MediaQueryList;
  }

  if (typeof window.requestAnimationFrame !== 'function') {
    window.requestAnimationFrame = (cb: FrameRequestCallback): number => {
      return window.setTimeout(() => cb(Date.now()), 16) as unknown as number;
    };
    window.cancelAnimationFrame = (id: number): void => {
      window.clearTimeout(id);
    };
  }
}