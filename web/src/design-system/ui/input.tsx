import type { ComponentProps } from "react";
import { cn } from "@/design-system/cn";

export function Input({ className, ...props }: ComponentProps<"input">) {
  return (
    <input
      className={cn(
        "h-10 w-full rounded-md border border-border-input bg-surface-raised px-3 text-sm text-fg placeholder:text-fg-muted",
        className,
      )}
      {...props}
    />
  );
}
