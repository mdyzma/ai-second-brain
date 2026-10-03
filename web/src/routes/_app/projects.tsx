import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/projects")({
  beforeLoad: () => {
    throw redirect({ to: "/entities", search: { type: "project" }, replace: true });
  },
});
