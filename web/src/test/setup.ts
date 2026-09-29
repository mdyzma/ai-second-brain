import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Files that opt into `@vitest-environment node` (SSE/fetch tests) have no DOM to reset.
const hasDom = typeof window !== "undefined";

afterEach(() => {
  if (!hasDom) return;
  cleanup();
  document.documentElement.removeAttribute("data-theme");
  window.localStorage.clear();
});

if (hasDom && typeof window.matchMedia !== "function") {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}
