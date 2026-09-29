import { Link } from "@tanstack/react-router";
import { LogOut } from "lucide-react";
import type { ReactNode } from "react";
import { NAV_ORDER, SCREENS } from "@/features/screens/screens";
import { cn } from "./cn";
import { ThemeToggle } from "./theme";
import { Button } from "./ui/button";

function NavLinks({ layout }: { layout: "sidebar" | "bar" }) {
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
                "flex items-center rounded-md",
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
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

export function AppShell({ children, onLogout }: { children: ReactNode; onLogout: () => void }) {
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
    </div>
  );
}
