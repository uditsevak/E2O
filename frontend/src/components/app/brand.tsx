import { InboxIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export const PRODUCT_NAME = "Enquiry Inbox";

export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "bg-primary text-primary-foreground inline-flex size-8 items-center justify-center rounded-lg",
        className,
      )}
    >
      <InboxIcon className="size-4.5" />
    </span>
  );
}

export function Brand({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 font-semibold tracking-tight", className)}>
      <BrandMark />
      {PRODUCT_NAME}
    </span>
  );
}
