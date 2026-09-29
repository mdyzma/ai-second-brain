import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";

const IGNORED_401_PATHS = new Set(["/api/auth/me", "/api/auth/login"]);

let onUnauthorized: (() => void) | undefined;

/** Called when any request other than me/login gets a 401 (the session ended). */
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

export const unauthorizedMiddleware: Middleware = {
  onResponse({ request, response }) {
    const path = new URL(request.url).pathname;
    if (response.status === 401 && !IGNORED_401_PATHS.has(path)) onUnauthorized?.();
    return undefined;
  },
};

export const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? "",
  credentials: "same-origin",
});
api.use(unauthorizedMiddleware);
