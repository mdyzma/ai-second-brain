import {
  FolderKanban,
  GitPullRequest,
  Library,
  type LucideIcon,
  MessageSquare,
  Network,
  Search,
  Server,
  Settings,
  Sunrise,
} from "lucide-react";

export type ScreenId =
  | "ask"
  | "search"
  | "projects"
  | "entities"
  | "digest"
  | "review"
  | "nodes"
  | "sources"
  | "settings";

type Screen = {
  path: `/${ScreenId}`;
  label: string;
  icon: LucideIcon;
  phase: string;
  purpose: string;
};

export const SCREENS: Record<ScreenId, Screen> = {
  ask: {
    path: "/ask",
    label: "Ask",
    icon: MessageSquare,
    phase: "1b",
    purpose: "Ask questions answered from your private memory, with sources shown first.",
  },
  search: {
    path: "/search",
    label: "Search",
    icon: Search,
    phase: "2",
    purpose: "Find notes and documents without generating an answer.",
  },
  projects: {
    path: "/projects",
    label: "Projects",
    icon: FolderKanban,
    phase: "8",
    purpose: "Resume any project: decisions, commits, open threads and where it runs.",
  },
  entities: {
    path: "/entities",
    label: "Entities",
    icon: Network,
    phase: "4a",
    purpose: "Browse the people, tools, devices and projects found in your notes.",
  },
  digest: {
    path: "/digest",
    label: "Digest",
    icon: Sunrise,
    phase: "4",
    purpose: "Your morning summary: new links, items to review and rediscovered ideas.",
  },
  review: {
    path: "/review",
    label: "Review",
    icon: GitPullRequest,
    phase: "4",
    purpose: "Accept or reject the links proposed by nightly consolidation.",
  },
  nodes: {
    path: "/nodes",
    label: "Nodes",
    icon: Server,
    phase: "5",
    purpose: "See and wake your machines: workstation, MacBook and Proxmox.",
  },
  sources: {
    path: "/sources",
    label: "Sources",
    icon: Library,
    phase: "2",
    purpose: "Ingestion status, sharing and pinning for every source.",
  },
  settings: {
    path: "/settings",
    label: "Settings",
    icon: Settings,
    phase: "1b",
    purpose: "Models, hosts, schedules and your login.",
  },
};

export const NAV_ORDER: ScreenId[] = [
  "ask",
  "search",
  "projects",
  "entities",
  "digest",
  "review",
  "nodes",
  "sources",
  "settings",
];
