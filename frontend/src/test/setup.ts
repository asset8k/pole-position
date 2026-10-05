import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeAll, vi } from 'vitest';

// jsdom doesn't implement native dialogs or media-query events. Browser tests
// exercise the real implementations, including native modal focus containment.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn((media: string) => ({
      media, matches: false, onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
    })),
  });
});

afterEach(cleanup);
