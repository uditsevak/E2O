"use client";

import Link from "next/link";
import { CheckIcon, ChevronsUpDownIcon, PlusIcon } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Me, Workspace } from "@/lib/queries";

export function WorkspaceSwitcher({ me, current }: { me: Me; current: Workspace }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="hover:bg-accent focus-visible:ring-ring flex min-w-0 items-center gap-1.5 rounded-md px-2 py-1.5 text-left outline-none focus-visible:ring-2">
        <span className="truncate font-semibold">{current.name}</span>
        <ChevronsUpDownIcon className="text-muted-foreground size-4 shrink-0" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">
          Your businesses
        </DropdownMenuLabel>
        {me.workspaces.map((w) => (
          <DropdownMenuItem key={w.id} asChild>
            <Link href={`/w/${w.id}`}>
              <span className="flex-1 truncate">{w.name}</span>
              {w.id === current.id && <CheckIcon className="text-primary" />}
            </Link>
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/onboarding">
            <PlusIcon /> Add another business
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
