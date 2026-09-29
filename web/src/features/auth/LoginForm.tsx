import { type FormEvent, useId, useState } from "react";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { Label } from "@/design-system/ui/label";
import { type LoginResult, login } from "./session";

type Failure = Exclude<LoginResult, { ok: true }>;

export function loginErrorMessage(result: Failure): string {
  switch (result.reason) {
    case "invalid":
      return "Incorrect password";
    case "throttled":
      return `Too many attempts, try again in ${result.retryAfter} s`;
    case "unreachable":
      return "Can't reach the server";
  }
}

type LoginFormProps = {
  onSuccess: () => void | Promise<void>;
  submit?: (password: string) => Promise<LoginResult>;
};

export function LoginForm({ onSuccess, submit = login }: LoginFormProps) {
  const passwordId = useId();
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const result = await submit(password);
      if (result.ok) {
        await onSuccess();
        return;
      }
      setError(loginErrorMessage(result));
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={handleSubmit} noValidate>
      <div className="flex flex-col gap-2">
        <Label htmlFor={passwordId}>Password</Label>
        <Input
          id={passwordId}
          type="password"
          autoComplete="current-password"
          maxLength={1024}
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </div>
      {error !== null && (
        <p
          role="alert"
          className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg"
        >
          {error}
        </p>
      )}
      <Button type="submit" disabled={pending} aria-disabled={pending}>
        {pending ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
