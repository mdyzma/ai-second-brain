import { createFileRoute } from "@tanstack/react-router";
import { PlaceholderScreen } from "@/features/screens/PlaceholderScreen";

export const Route = createFileRoute("/_app/review")({
  component: () => <PlaceholderScreen id="review" />,
});
