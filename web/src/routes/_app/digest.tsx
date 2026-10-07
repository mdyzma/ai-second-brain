import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { DigestScreen } from "@/features/digest/DigestScreen";

type DigestSearch = { run?: string };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const Route = createFileRoute("/_app/digest")({
  validateSearch: (raw: Record<string, unknown>): DigestSearch =>
    typeof raw.run === "string" && UUID.test(raw.run) ? { run: raw.run } : {},
  component: DigestRoute,
});

function DigestRoute() {
  const { run } = Route.useSearch();
  const navigate = useNavigate({ from: Route.fullPath });
  return (
    <DigestScreen
      runId={run}
      onRun={(next) => void navigate({ search: next ? { run: next } : {} })}
    />
  );
}
