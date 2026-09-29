import { Card } from "@/design-system/ui/card";
import { SCREENS, type ScreenId } from "./screens";

export function PlaceholderScreen({ id }: { id: ScreenId }) {
  const screen = SCREENS[id];
  const Icon = screen.icon;
  return (
    <Card className="max-w-2xl">
      <div className="flex items-center gap-3">
        <Icon aria-hidden className="size-6 text-fg-muted" />
        <h1 className="text-2xl font-semibold">{screen.label}</h1>
      </div>
      <p className="mt-3 text-fg-muted">{screen.purpose}</p>
      <p className="mt-4 text-sm font-medium">Arrives in phase {screen.phase}</p>
    </Card>
  );
}
