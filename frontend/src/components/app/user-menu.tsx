"use client";

import { useRouter } from "next/navigation";
import { LogOutIcon } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { initials } from "@/lib/format";
import { useLogout, type Me } from "@/lib/queries";

export function Avatar({ name, className = "" }: { name: string; className?: string }) {
  return (
    <span
      className={`bg-secondary text-secondary-foreground inline-flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${className}`}
    >
      {initials(name)}
    </span>
  );
}

export function UserMenu({ me, showName = false }: { me: Me; showName?: boolean }) {
  const logout = useLogout();
  const router = useRouter();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="hover:bg-accent focus-visible:ring-ring flex min-w-0 items-center gap-2 rounded-md p-1 text-left outline-none focus-visible:ring-2">
        <Avatar name={me.user.name} />
        {showName && (
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium">{me.user.name}</span>
            <span className="text-muted-foreground block truncate text-xs">{me.user.email}</span>
          </span>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>
          <span className="block">{me.user.name}</span>
          <span className="text-muted-foreground block text-xs font-normal">{me.user.email}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={async () => {
            await logout.mutateAsync();
            router.replace("/login");
          }}
        >
          <LogOutIcon /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
