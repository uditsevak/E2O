import { LockIcon } from "lucide-react";

import { Brand } from "@/components/app/brand";

export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex justify-center">
          <Brand className="text-lg" />
        </div>
        <div className="bg-card rounded-xl border p-6 shadow-xs">
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="text-muted-foreground mt-1 text-sm">{subtitle}</p>}
          <div className="mt-6">{children}</div>
        </div>
        {footer && <div className="text-muted-foreground mt-4 text-center text-sm">{footer}</div>}
        <p className="text-muted-foreground mt-8 flex items-center justify-center gap-1.5 text-xs">
          <LockIcon className="size-3" /> Your data stays private to your business.
        </p>
      </div>
    </main>
  );
}
