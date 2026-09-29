import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LoginForm } from "./LoginForm";
import type { LoginResult } from "./session";

async function submitWith(result: LoginResult) {
  const onSuccess = vi.fn();
  const user = userEvent.setup();
  render(<LoginForm onSuccess={onSuccess} submit={async () => result} />);
  await user.type(screen.getByLabelText("Password"), "hunter2");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  return onSuccess;
}

describe("LoginForm", () => {
  it("calls onSuccess on ok", async () => {
    const onSuccess = await submitWith({ ok: true });
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    [{ ok: false, reason: "invalid" } as const, "Incorrect password"],
    [
      { ok: false, reason: "throttled", retryAfter: 42 } as const,
      "Too many attempts, try again in 42 s",
    ],
    [{ ok: false, reason: "unreachable" } as const, "Can't reach the server"],
  ])("shows an alert for %o", async (result, message) => {
    const onSuccess = await submitWith(result);
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("shows a pending state and ignores double submit", async () => {
    let resolveLogin: (r: LoginResult) => void = () => {};
    const submit = vi.fn(
      () =>
        new Promise<LoginResult>((resolve) => {
          resolveLogin = resolve;
        }),
    );
    const user = userEvent.setup();
    render(<LoginForm onSuccess={vi.fn()} submit={submit} />);
    await user.type(screen.getByLabelText("Password"), "pw");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    const pending = screen.getByRole("button", { name: "Signing in…" });
    expect(pending).toBeDisabled();
    await user.click(pending);
    expect(submit).toHaveBeenCalledTimes(1);
    resolveLogin({ ok: false, reason: "invalid" });
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("stays pending until onSuccess has completed", async () => {
    let finish: () => void = () => {};
    const onSuccess = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const user = userEvent.setup();
    render(<LoginForm onSuccess={onSuccess} submit={async () => ({ ok: true })} />);
    await user.type(screen.getByLabelText("Password"), "pw");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("button", { name: "Signing in…" })).toBeDisabled();
    finish();
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("password field is labelled and uses current-password autocomplete", () => {
    render(<LoginForm onSuccess={vi.fn()} />);
    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("type", "password");
    expect(input).toHaveAttribute("autocomplete", "current-password");
    expect(input).toHaveAttribute("maxlength", "1024");
  });
});
