import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { entityQuery } from "@/features/graph/api";
import { EntityScreen } from "@/features/graph/EntityScreen";
import { statusOf } from "@/features/sources/api";

export const Route = createFileRoute("/_app/entities/$entityId")({ component: EntityRoute });

function EntityRoute() {
  const { entityId } = Route.useParams();
  const entity = useQuery(entityQuery(entityId));
  return (
    <EntityScreen entity={entity.data} error={entity.isError ? statusOf(entity.error) : null} />
  );
}
