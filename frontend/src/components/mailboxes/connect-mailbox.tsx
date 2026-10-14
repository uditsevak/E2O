"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangleIcon,
  ArrowLeftIcon,
  CheckCircle2Icon,
  ChevronRightIcon,
  ExternalLinkIcon,
  Loader2Icon,
  MailIcon,
  ServerIcon,
} from "lucide-react";
import { toast } from "sonner";

import { ErrorState, ListSkeleton, PageHeader } from "@/components/app/states";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { errorMessage } from "@/lib/api/client";
import {
  useConnectImap,
  usePresets,
  useTestImap,
  type ImapPreset,
  type ImapTest,
} from "@/lib/queries";
import { useWorkspace } from "@/lib/use-workspace";
import { cn } from "@/lib/utils";

import { TrustPanel } from "./trust-panel";
import { useFieldId } from "@/lib/use-field-id";

const SECURITY_LABEL: Record<string, string> = { ssl: "SSL", starttls: "STARTTLS", none: "None" };

function ProviderPicker({
  presets,
  onPick,
}: {
  presets: ImapPreset[];
  onPick: (p: ImapPreset) => void;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {presets.map((p) => (
        <button
          key={p.id}
          disabled={!p.available}
          onClick={() => onPick(p)}
          className="bg-card hover:border-primary/40 hover:bg-accent/50 disabled:hover:bg-card flex items-center gap-3 rounded-lg border p-4 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60"
        >
          <span className="bg-accent text-primary flex size-9 shrink-0 items-center justify-center rounded-full">
            {p.host ? <MailIcon className="size-4" /> : <ServerIcon className="size-4" />}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-medium">{p.label}</span>
            <span className="text-muted-foreground block text-xs">
              {p.available ? (p.host ?? "Enter your mail server") : "Coming soon"}
            </span>
          </span>
          {p.available && <ChevronRightIcon className="text-muted-foreground size-4" />}
        </button>
      ))}
    </div>
  );
}

type Form = {
  email: string;
  password: string;
  displayName: string;
  host: string;
  port: string;
  security: "ssl" | "starttls" | "none";
  username: string;
  backfillDays: string;
  tlsVerify: boolean;
};

function DetailsForm({ preset, onBack }: { preset: ImapPreset; onBack: () => void }) {
  const fid = useFieldId();
  const { wid } = useWorkspace();
  const router = useRouter();
  const test = useTestImap(wid);
  const connect = useConnectImap(wid);
  const [form, setForm] = useState<Form>({
    email: "",
    password: "",
    displayName: "",
    host: preset.host ?? "",
    port: String(preset.port),
    security: preset.security as Form["security"],
    username: "",
    backfillDays: "30",
    tlsVerify: true,
  });
  const [showServer, setShowServer] = useState(!preset.host);
  const [result, setResult] = useState<ImapTest | null>(null);
  const [inbound, setInbound] = useState<string>("");
  const [outbound, setOutbound] = useState<string>("");

  const set = <K extends keyof Form>(key: K, value: Form[K], resetTest = true) => {
    setForm((f) => ({ ...f, [key]: value }));
    if (resetTest) setResult(null);
  };

  const settings = useMemo(
    () => ({
      host: form.host.trim(),
      port: Number(form.port) || 993,
      security: form.security,
      username: (form.username || form.email).trim(),
      password: form.password,
      tls_verify: form.tlsVerify,
    }),
    [form],
  );

  const runTest = () =>
    test.mutate(settings, {
      onSuccess: (r) => {
        setResult(r);
        if (r.ok) {
          setInbound(r.inbound_folder ?? "INBOX");
          setOutbound(r.outbound_folder ?? "");
        }
      },
    });

  const tested = result?.ok === true;
  const certProblem = result?.error_code === "tls_cert";

  return (
    <div className="grid gap-6 md:grid-cols-[1fr_20rem]">
      <form
        className="space-y-5"
        onSubmit={(e) => {
          e.preventDefault();
          if (!tested) return runTest();
          connect.mutate(
            {
              ...settings,
              email: form.email.trim(),
              display_name: form.displayName.trim() || null,
              backfill_days: Number(form.backfillDays),
              inbound_folder: inbound || null,
              outbound_folder: outbound || null,
            },
            {
              onSuccess: () => {
                toast.success("Mailbox connected. Bringing in your emails…");
                router.push(`/w/${wid}/mailboxes`);
              },
            },
          );
        }}
      >
        <button
          type="button"
          onClick={onBack}
          className="text-muted-foreground hover:text-foreground flex items-center gap-1 text-sm"
        >
          <ArrowLeftIcon className="size-4" /> {preset.label}
        </button>

        <Alert>
          <AlertDescription>
            <p>{preset.help}</p>
            {preset.help_url && (
              <a
                href={preset.help_url}
                target="_blank"
                rel="noreferrer"
                className="text-primary inline-flex items-center gap-1 font-medium"
              >
                How to do this <ExternalLinkIcon className="size-3" />
              </a>
            )}
          </AlertDescription>
        </Alert>

        <div className="space-y-2">
          <Label htmlFor={fid("email")}>Email address</Label>
          <Input
            id={fid("email")}
            type="email"
            autoComplete="off"
            placeholder="sales@yourcompany.com"
            required
            value={form.email}
            onChange={(e) => set("email", e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={fid("password")}>
            {preset.id === "gmail" || preset.id.startsWith("zoho") ? "App password" : "Password"}
          </Label>
          <Input
            id={fid("password")}
            type="password"
            autoComplete="new-password"
            required
            value={form.password}
            onChange={(e) => set("password", e.target.value)}
          />
        </div>

        <div className="rounded-lg border">
          <button
            type="button"
            className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left text-sm"
            onClick={() => setShowServer((v) => !v)}
          >
            <span>
              <span className="font-medium">Server settings</span>
              {!showServer && (
                <span className="text-muted-foreground ml-2">
                  {form.host || "not set"} · {form.port} · {SECURITY_LABEL[form.security]}
                </span>
              )}
            </span>
            <ChevronRightIcon
              className={cn(
                "text-muted-foreground size-4 transition-transform",
                showServer && "rotate-90",
              )}
            />
          </button>
          {showServer && (
            <div className="grid gap-4 border-t p-4 sm:grid-cols-2">
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor={fid("host")}>IMAP server</Label>
                <Input
                  id={fid("host")}
                  placeholder="mail.yourcompany.com"
                  required
                  value={form.host}
                  onChange={(e) => set("host", e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor={fid("port")}>Port</Label>
                <Input
                  id={fid("port")}
                  inputMode="numeric"
                  value={form.port}
                  onChange={(e) => set("port", e.target.value.replace(/\D/g, ""))}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor={fid("security")}>Security</Label>
                <NativeSelect
                  id={fid("security")}
                  value={form.security}
                  onChange={(e) => set("security", e.target.value as Form["security"])}
                >
                  <option value="ssl">SSL (port 993)</option>
                  <option value="starttls">STARTTLS (port 143)</option>
                  <option value="none">None (not recommended)</option>
                </NativeSelect>
              </div>
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor={fid("username")}>Username</Label>
                <Input
                  id={fid("username")}
                  placeholder={form.email || "Usually your full email address"}
                  value={form.username}
                  onChange={(e) => set("username", e.target.value)}
                />
              </div>
            </div>
          )}
        </div>

        {result && !result.ok && (
          <Alert variant="destructive">
            <AlertTriangleIcon />
            <AlertTitle>Couldn&apos;t connect</AlertTitle>
            <AlertDescription>
              <p>{result.error}</p>
              {certProblem && (
                <label className="text-foreground mt-2 flex items-start gap-2">
                  <input
                    type="checkbox"
                    className="mt-0.5 size-4"
                    checked={!form.tlsVerify}
                    onChange={(e) => set("tlsVerify", !e.target.checked, false)}
                  />
                  <span>Allow this server&apos;s certificate anyway (less secure)</span>
                </label>
              )}
            </AlertDescription>
          </Alert>
        )}
        {test.error && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(test.error)}</AlertDescription>
          </Alert>
        )}

        {tested && result && (
          <div className="border-success/30 bg-success/5 space-y-4 rounded-lg border p-4">
            <div className="flex items-center gap-2 text-sm font-medium">
              <CheckCircle2Icon className="text-success size-4" /> Connected. We found these
              folders:
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor={fid("inbound")}>Received emails</Label>
                <NativeSelect
                  id={fid("inbound")}
                  value={inbound}
                  onChange={(e) => setInbound(e.target.value)}
                >
                  {result.folders.map((f) => (
                    <option key={f.name} value={f.name}>
                      {f.display_name}
                    </option>
                  ))}
                </NativeSelect>
              </div>
              <div className="space-y-2">
                <Label htmlFor={fid("outbound")}>Sent emails</Label>
                <NativeSelect
                  id={fid("outbound")}
                  value={outbound}
                  onChange={(e) => setOutbound(e.target.value)}
                >
                  <option value="">(none)</option>
                  {result.folders.map((f) => (
                    <option key={f.name} value={f.name}>
                      {f.display_name}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            </div>
            {!outbound && (
              <p className="text-muted-foreground text-sm">
                Pick your Sent folder so we can see when your team has replied to an enquiry.
              </p>
            )}
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor={fid("display-name")}>Name for this mailbox</Label>
                <Input
                  id={fid("display-name")}
                  placeholder={form.email}
                  value={form.displayName}
                  onChange={(e) => set("displayName", e.target.value, false)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor={fid("backfill")}>Bring in past emails</Label>
                <NativeSelect
                  id={fid("backfill")}
                  value={form.backfillDays}
                  onChange={(e) => set("backfillDays", e.target.value, false)}
                >
                  <option value="7">Last 7 days</option>
                  <option value="30">Last 30 days</option>
                  <option value="90">Last 90 days</option>
                  <option value="0">Only new emails from now</option>
                </NativeSelect>
              </div>
            </div>
          </div>
        )}

        {connect.error && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(connect.error)}</AlertDescription>
          </Alert>
        )}

        <Button
          type="submit"
          size="lg"
          className="w-full sm:w-auto"
          disabled={test.isPending || connect.isPending}
        >
          {(test.isPending || connect.isPending) && <Loader2Icon className="animate-spin" />}
          {tested ? "Connect mailbox" : test.isPending ? "Checking…" : "Test connection"}
        </Button>
      </form>
      <TrustPanel />
    </div>
  );
}

export function ConnectMailbox() {
  const { wid, isAdmin } = useWorkspace();
  const presets = usePresets();
  const [preset, setPreset] = useState<ImapPreset | null>(null);

  if (!isAdmin) {
    return (
      <>
        <PageHeader title="Connect a mailbox" />
        <p className="text-muted-foreground text-sm">
          Only the workspace owner or an admin can connect mailboxes.{" "}
          <Link className="text-primary underline" href={`/w/${wid}/mailboxes`}>
            Back to mailboxes
          </Link>
        </p>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Connect a mailbox"
        description={preset ? undefined : "Where does this mailbox live?"}
      />
      {presets.isPending ? (
        <ListSkeleton rows={3} />
      ) : presets.error ? (
        <ErrorState error={presets.error} onRetry={() => presets.refetch()} />
      ) : preset ? (
        <DetailsForm key={preset.id} preset={preset} onBack={() => setPreset(null)} />
      ) : (
        <div className="grid gap-6 md:grid-cols-[1fr_20rem]">
          <ProviderPicker presets={presets.data} onPick={setPreset} />
          <TrustPanel />
        </div>
      )}
    </>
  );
}
