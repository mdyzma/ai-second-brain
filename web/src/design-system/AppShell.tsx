import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { LogOut, PenLine } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { isObsidianUrl } from "@/api/obsidian";
import type { Captured } from "@/features/capture/api";
import { CaptureDialog } from "@/features/capture/CaptureDialog";
import { digestQuery } from "@/features/digest/api";
import { NAV_ORDER, SCREENS } from "@/features/screens/screens";
import { cn } from "./cn";
import { ThemeToggle } from "./theme";
import { Button } from "./ui/button";

function NavLinks({ layout }: { layout: "sidebar" | "bar" }) {
  const digest = useQuery(digestQuery());
  // Everything awaiting review, from any run: a quiet night must not hide older items.
  const remaining = digest.data?.review?.open_total ?? 0;
  return (
    <ul
      className={cn(
        layout === "sidebar"
          ? "flex flex-col gap-1 px-2"
          : "flex justify-between overflow-x-auto px-1",
      )}
    >
      {NAV_ORDER.map((id) => {
        const screen = SCREENS[id];
        const Icon = screen.icon;
        return (
          <li key={id}>
            <Link
              to={screen.path}
              className={cn(
                "group relative flex items-center rounded-md",
                layout === "sidebar"
                  ? "gap-3 px-3 py-2 text-sm"
                  : "min-w-12 flex-col gap-1 px-2 py-2 text-xs",
              )}
              inactiveProps={{
                className: "text-fg-muted hover:bg-surface-raised hover:text-fg",
              }}
              activeProps={{ className: "bg-accent text-accent-fg", "aria-current": "page" }}
            >
              <Icon aria-hidden className="size-4" />
              <span>{screen.label}</span>
              {id === "digest" && remaining > 0 ? (
                <>
                  {" "}
                  <span
                    className={cn(
                      "rounded-full bg-accent px-1.5 text-xs text-accent-fg",
                      // On the active (accent) item the badge inverts so it stays visible.
                      "group-aria-[current=page]:bg-accent-fg group-aria-[current=page]:text-accent",
                      // In the phone bar the badge overlays the icon so the item keeps its size.
                      layout === "sidebar" ? "ml-auto" : "absolute top-0.5 right-0.5",
                    )}
                  >
                    {remaining}
                    {/* The accessible-name algorithm trims the span's own leading space. */}{" "}
                    <span className="sr-only"> to review</span>
                  </span>
                </>
              ) : null}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

const STATUS_MS = 6000;

export function AppShell({ children, onLogout }: { children: ReactNode; onLogout: () => void }) {
  const [captureOpen, setCaptureOpen] = useState(false);
  const [saved, setSaved] = useState<Captured | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const openRef = useRef(captureOpen);
  openRef.current = captureOpen;

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (
        e.defaultPrevented ||
        e.isComposing ||
        e.key !== "c" ||
        e.ctrlKey ||
        e.metaKey ||
        e.altKey ||
        e.shiftKey
      )
        return;
      if (openRef.current) return;
      const t = e.target as HTMLElement | null;
      const typing =
        t !== null && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));
      if (typing) return;
      e.preventDefault();
      setCaptureOpen(true);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => () => clearTimeout(timer.current), []);

  function onSaved(result: Captured) {
    clearTimeout(timer.current);
    setSaved(result);
    timer.current = setTimeout(() => setSaved(null), STATUS_MS);
  }

  return (
    <div className="min-h-dvh bg-bg text-fg md:grid md:grid-cols-[14rem_1fr]">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-surface-raised focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <aside className="hidden border-r border-border bg-surface md:block">
        <div className="px-5 py-4 font-semibold">Second Brain</div>
        <nav aria-label="Primary">
          <NavLinks layout="sidebar" />
        </nav>
      </aside>
      <div className="flex min-h-dvh flex-col pb-20 md:pb-0">
        <header className="flex items-center justify-between border-b border-border px-4 py-2">
          <span className="font-semibold md:invisible">Second Brain</span>
          <div className="flex items-center gap-1">
            <div role="status" className="text-sm text-fg-muted">
              {saved ? (
                <>
                  <span>Saved to Inbox</span>
                  {isObsidianUrl(saved.obsidian_url) ? (
                    <>
                      {" · "}
                      <a href={saved.obsidian_url} className="text-accent underline">
                        Open in Obsidian
                      </a>
                    </>
                  ) : null}
                </>
              ) : null}
            </div>
            <Button variant="ghost" size="sm" onClick={() => setCaptureOpen(true)}>
              <PenLine aria-hidden />
              Capture
            </Button>
            <ThemeToggle />
            <Button variant="ghost" size="sm" onClick={onLogout}>
              <LogOut aria-hidden />
              Log out
            </Button>
          </div>
        </header>
        <main id="main-content" tabIndex={-1} className="flex-1 p-4 md:p-8">
          {children}
        </main>
      </div>
      <nav
        aria-label="Primary"
        className="fixed inset-x-0 bottom-0 border-t border-border bg-surface md:hidden"
      >
        <NavLinks layout="bar" />
      </nav>
      <CaptureDialog open={captureOpen} onOpenChange={setCaptureOpen} onSaved={onSaved} />
    </div>
  );
}
