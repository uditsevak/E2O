const timeFmt = new Intl.DateTimeFormat("en-IN", { hour: "numeric", minute: "2-digit" });
const dayMonthFmt = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });
const fullFmt = new Intl.DateTimeFormat("en-IN", {
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** "10:24 am" today, "Yesterday", "12 Oct" this year, "12 Oct 2025" otherwise. */
export function shortDate(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  const now = new Date();
  const days = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000);
  if (days === 0) return timeFmt.format(date);
  if (days === 1) return "Yesterday";
  if (date.getFullYear() === now.getFullYear()) return dayMonthFmt.format(date);
  return `${dayMonthFmt.format(date)} ${date.getFullYear()}`;
}

export function fullDate(value: string | null | undefined): string {
  return value ? fullFmt.format(new Date(value)) : "";
}

/** "just now", "5 min ago", "3 hours ago", "2 days ago". */
export function timeAgo(value: string | null | undefined): string {
  if (!value) return "never";
  const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function initials(name: string | null | undefined, fallback = "?"): string {
  const source = (name ?? "").trim();
  if (!source) return fallback;
  const parts = source
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
  const letters = parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : source.slice(0, 2);
  return letters.toUpperCase();
}

export function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export function plural(n: number, word: string, pluralWord = `${word}s`): string {
  return `${n.toLocaleString("en-IN")} ${n === 1 ? word : pluralWord}`;
}
