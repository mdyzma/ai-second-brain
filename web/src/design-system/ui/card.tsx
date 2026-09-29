import type { ComponentProps } from "react";
import { cn } from "@/design-system/cn";

export function Card({ className, ...props }: ComponentProps<"section">) {
  return (
    <section
      className={cn("rounded-lg border border-border bg-surface-raised p-6 text-fg", className)}
      {...props}
    />
  );
}
