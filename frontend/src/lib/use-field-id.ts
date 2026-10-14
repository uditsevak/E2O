import { useId } from "react";

/**
 * Unique ids for form fields. Next.js keeps recently visited pages mounted (hidden), so a
 * fixed id like "name" can exist twice in the DOM and a <label> would point at the wrong input.
 */
export function useFieldId() {
  const base = useId();
  return (name: string) => `${base}-${name}`;
}
