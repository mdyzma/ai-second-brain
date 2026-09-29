import { useId } from "react";
import { cn } from "@/design-system/cn";
import type { ChatMode } from "../types";

type Props = { value: ChatMode; onChange: (mode: ChatMode) => void; cloudAvailable: boolean };

export function ModeSwitcher({ value, onChange, cloudAvailable }: Props) {
  const name = useId();
  const options = [
    {
      mode: "private" as const,
      title: "Private",
      detail: "Answered by your local model. Nothing leaves your network.",
      disabled: false,
    },
    {
      mode: "cloud" as const,
      title: "Cloud",
      detail: cloudAvailable
        ? "Local memory is off. What you type is sent to Anthropic."
        : "Cloud mode needs SB_ANTHROPIC_API_KEY.",
      disabled: !cloudAvailable,
    },
  ];
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-sm font-medium">Where should this conversation go?</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {options.map((option) => (
          <label
            key={option.mode}
            className={cn(
              "flex cursor-pointer gap-3 rounded-md border border-border bg-surface-raised p-3",
              value === option.mode && "border-accent",
              option.disabled && "cursor-not-allowed opacity-60",
            )}
          >
            <input
              type="radio"
              name={name}
              value={option.mode}
              checked={value === option.mode}
              disabled={option.disabled}
              onChange={() => onChange(option.mode)}
              className="mt-1"
            />
            <span className="flex flex-col gap-0.5">
              <span className="text-sm font-medium">{option.title}</span>
              <span className="text-sm text-fg-muted">{option.detail}</span>
            </span>
          </label>
        ))}
      </div>
      <p className="text-xs text-fg-muted">
        The mode can't change later; start a new conversation to switch.
      </p>
    </fieldset>
  );
}
