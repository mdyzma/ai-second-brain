import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { DigestScreen } from "@/features/digest/DigestScreen";

type DigestSearch = { date?: string };

const DATE = /^\d{4}-\d{2}-\d{2}$/;

export const Route = createFileRoute("/_app/digest")({
  validateSearch: (raw: Record<string, unknown>): DigestSearch =>
    typeof raw.date === "string" && DATE.test(raw.date) ? { date: raw.date } : {},
  component: DigestRoute,
});

function DigestRoute() {
  const { date } = Route.useSearch();
  const navigate = useNavigate({ from: Route.fullPath });
  return (
    <DigestScreen
      date={date}
      onDate={(next) => void navigate({ search: next ? { date: next } : {} })}
    />
  );
}
