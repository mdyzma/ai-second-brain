import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Outlet, useNavigate } from "@tanstack/react-router";
import { AppShell } from "@/design-system/AppShell";
import { requireSession } from "@/features/auth/guard";
import { logout, sessionQueryKey } from "@/features/auth/session";

export const Route = createFileRoute("/_app")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: AppLayout,
});

function AppLayout() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    queryClient.setQueryData(sessionQueryKey, null);
    await navigate({ to: "/login", search: {} });
  }

  return (
    <AppShell onLogout={handleLogout}>
      <Outlet />
    </AppShell>
  );
}
