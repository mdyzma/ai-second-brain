import { Cloud, Lock, TriangleAlert } from "lucide-react";
import { cn } from "@/design-system/cn";
import { type TierDisplay, tierLabel } from "../tier";

const STYLES = {
  private: "border-tier-private-border bg-tier-private-bg text-tier-private-fg",
  degraded: "border-warning-border bg-warning-bg text-warning-fg",
  cloud: "border-tier-cloud-border bg-tier-cloud-bg text-tier-cloud-fg",
} as const;

export function TierBadge({ tier, className }: { tier: TierDisplay; className?: string }) {
  const cloud = tier.kind === "cloud";
  const warn = tier.kind === "private-unavailable" || (tier.kind === "private" && tier.degraded);
  const Icon = cloud ? Cloud : warn ? TriangleAlert : Lock;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium",
        cloud ? STYLES.cloud : warn ? STYLES.degraded : STYLES.private,
        className,
      )}
    >
      <Icon aria-hidden className="size-3.5 shrink-0" />
      <span>{tierLabel(tier)}</span>
    </span>
  );
}
