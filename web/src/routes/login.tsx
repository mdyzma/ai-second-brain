import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, redirect, useRouter } from "@tanstack/react-router";
import { Card } from "@/design-system/ui/card";
import { LoginForm } from "@/features/auth/LoginForm";
import { safeRedirect, sessionQueryKey, sessionQueryOptions } from "@/features/auth/session";

type LoginSearch = { redirect?: string };

export const Route = createFileRoute("/login")({
  validateSearch: (search: Record<string, unknown>): LoginSearch =>
    typeof search.redirect === "string" ? { redirect: search.redirect } : {},
  beforeLoad: async ({ context, search }) => {
    const session = await context.queryClient
      .ensureQueryData(sessionQueryOptions)
      .catch(() => null);
    if (session) throw redirect({ href: safeRedirect(search.redirect) });
  },
  component: LoginPage,
});

function LoginPage() {
  const { redirect: target } = Route.useSearch();
  const queryClient = useQueryClient();
  const router = useRouter();

  async function handleSuccess() {
    await queryClient.invalidateQueries({ queryKey: sessionQueryKey });
    await router.navigate({ href: safeRedirect(target) });
  }

  return (
    <div className="grid min-h-dvh place-items-center bg-bg p-4 text-fg">
      <Card className="w-full max-w-sm">
        <h1 className="mb-1 text-xl font-semibold">Second Brain</h1>
        <p className="mb-6 text-sm text-fg-muted">Sign in to your private memory.</p>
        <LoginForm onSuccess={handleSuccess} />
      </Card>
    </div>
  );
}
