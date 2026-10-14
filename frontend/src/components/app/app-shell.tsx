"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { InboxIcon, LayoutDashboardIcon, MailPlusIcon, UsersIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import type { Me } from "@/lib/queries";

import { Brand } from "./brand";
import { RequireAuth } from "./require-auth";
import { EmptyState } from "./states";
import { UserMenu } from "./user-menu";
import { WorkspaceSwitcher } from "./workspace-switcher";

const NAV = [
  { href: "", label: "Overview", icon: LayoutDashboardIcon },
  { href: "/emails", label: "Emails", icon: InboxIcon },
  { href: "/mailboxes", label: "Mailboxes", icon: MailPlusIcon },
  { href: "/team", label: "Team", icon: UsersIcon },
];

function useActive(base: string) {
  const pathname = usePathname();
  return (href: string) =>
    href === ""
      ? pathname === base
      : pathname === base + href || pathname.startsWith(`${base + href}/`);
}

function Shell({ me, children }: { me: Me; children: React.ReactNode }) {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const base = `/w/${workspaceId}`;
  const isActive = useActive(base);
  const workspace = me.workspaces.find((w) => w.id === workspaceId);

  if (!workspace) {
    return (
      <main className="mx-auto w-full max-w-md p-6">
        <EmptyState icon={<InboxIcon />} title="Workspace not found">
          You may not have access to it any more.{" "}
          <Link className="text-primary underline" href="/">
            Go to your workspace
          </Link>
        </EmptyState>
      </main>
    );
  }

  return (
    <div className="flex min-h-dvh w-full">
      {/* Desktop sidebar */}
      <aside className="bg-card sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r md:flex">
        <div className="px-4 py-4">
          <Brand />
        </div>
        <div className="px-2">
          <WorkspaceSwitcher me={me} current={workspace} />
        </div>
        <nav className="mt-4 flex flex-col gap-0.5 px-2">
          {NAV.map(({ href, label, icon: Icon }) => (
            <Link
              key={label}
              href={base + href}
              className={cn(
                "text-muted-foreground hover:bg-accent hover:text-foreground flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive(href) && "bg-accent text-foreground",
              )}
            >
              <Icon className={cn("size-4", isActive(href) && "text-primary")} />
              {label}
            </Link>
          ))}
        </nav>
        <div className="mt-auto border-t p-2">
          <UserMenu me={me} showName />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile top bar */}
        <header className="bg-card/95 sticky top-0 z-30 flex h-14 items-center justify-between gap-2 border-b px-3 backdrop-blur md:hidden">
          <WorkspaceSwitcher me={me} current={workspace} />
          <UserMenu me={me} />
        </header>

        <main className="mx-auto w-full max-w-5xl flex-1 px-4 pt-5 pb-24 md:px-8 md:pt-8 md:pb-10">
          {children}
        </main>

        {/* Mobile bottom navigation */}
        <nav className="bg-card/95 fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
          {NAV.map(({ href, label, icon: Icon }) => (
            <Link
              key={label}
              href={base + href}
              className={cn(
                "text-muted-foreground flex flex-col items-center gap-1 py-2 text-[11px] font-medium",
                isActive(href) && "text-primary",
              )}
            >
              <Icon className="size-5" />
              {label}
            </Link>
          ))}
        </nav>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return <RequireAuth>{(me) => <Shell me={me}>{children}</Shell>}</RequireAuth>;
}
