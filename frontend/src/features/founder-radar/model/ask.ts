/**
 * The form dialog that replaces v1's window.prompt() / confirm() chains (the old `AskDialog`): a spec says which fields
 * to ask, and `confirm(values)` adds v1's explicit confirmation step (a summary, then a second button press).
 */
export type AskField = {
  name: string;
  label: string;
  type?: "text" | "textarea" | "date" | "select" | "checkbox";
  placeholder?: string;
  options?: Array<string | { value: string; label: string }>;
  initial?: string | boolean;
  required?: boolean;
  hint?: string;
  /** Only shown when another field has this value, e.g. { field: "field", equals: "recent_activity" }. */
  when?: { field: string; equals: string };
};

export type Values = Record<string, string | boolean>;

export type AskSpec = {
  title: string;
  intro?: string;
  fields: AskField[];
  submitLabel?: string;
  confirm?: (v: Values) => string;
};

/** String value of a dialog field ("" when absent). */
export const sv = (v: Values, k: string): string => (typeof v[k] === "string" ? (v[k] as string) : "");

/** The values a dialog opens with: each field's `initial`, else "" (false for a checkbox). */
export const initialValues = (fields: AskField[]): Values =>
  Object.fromEntries(fields.map((f) => [f.name, f.initial ?? (f.type === "checkbox" ? false : "")]));

/** The fields shown for these values (a `when` field only while its condition holds). */
export const visibleFields = (fields: AskField[], v: Values): AskField[] => fields.filter((f) => !f.when || v[f.when.field] === f.when.equals);

/** True while a shown required field is empty: the dialog's OK stays disabled. */
export const missingRequired = (fields: AskField[], v: Values): boolean =>
  visibleFields(fields, v).some((f) => f.required && !String(v[f.name] ?? "").trim());
