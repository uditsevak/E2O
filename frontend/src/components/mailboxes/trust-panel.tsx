import { CheckIcon, ShieldCheckIcon } from "lucide-react";

const POINTS = [
  "We only read. We never send, delete, move or mark your emails as read.",
  "We read your Inbox to find enquiries, and your Sent folder to see when your team replied.",
  "Your password is encrypted and used only to read this mailbox.",
  "Disconnect any time. We delete the stored password straight away.",
];

export function TrustPanel() {
  return (
    <div className="bg-accent/40 rounded-xl border p-4">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <ShieldCheckIcon className="text-success size-4" /> What we read, and why
      </div>
      <ul className="text-muted-foreground mt-3 space-y-2 text-sm">
        {POINTS.map((p) => (
          <li key={p} className="flex gap-2">
            <CheckIcon className="text-success mt-0.5 size-4 shrink-0" />
            <span>{p}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
