import {
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

import { cn } from "@/lib/utils/format";

const CONTROL =
  "block w-full min-h-11 rounded-lg border bg-surface px-3 py-2 text-sm text-ink " +
  "placeholder:text-muted/70 disabled:bg-canvas disabled:text-muted";

function controlClasses(error?: string) {
  return cn(CONTROL, error ? "border-red-600" : "border-line");
}

type FieldFrameProps = {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
};

function FieldFrame({ id, label, hint, error, children }: FieldFrameProps) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium text-ink">
        {label}
      </label>
      {children}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-xs text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-xs font-medium text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}

function describedBy(id: string, hint?: string, error?: string) {
  if (error) return `${id}-error`;
  if (hint) return `${id}-hint`;
  return undefined;
}

type Common = { label: string; hint?: string; error?: string };

export function Input({
  label,
  hint,
  error,
  id: givenId,
  className,
  ...props
}: Common & InputHTMLAttributes<HTMLInputElement>) {
  const generated = useId();
  const id = givenId ?? generated;
  return (
    <FieldFrame id={id} label={label} hint={hint} error={error}>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
        className={cn(controlClasses(error), className)}
        {...props}
      />
    </FieldFrame>
  );
}

export function Textarea({
  label,
  hint,
  error,
  id: givenId,
  className,
  ...props
}: Common & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const generated = useId();
  const id = givenId ?? generated;
  return (
    <FieldFrame id={id} label={label} hint={hint} error={error}>
      <textarea
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
        className={cn(controlClasses(error), "min-h-24", className)}
        {...props}
      />
    </FieldFrame>
  );
}

export function Select({
  label,
  hint,
  error,
  id: givenId,
  className,
  options,
  ...props
}: Common &
  SelectHTMLAttributes<HTMLSelectElement> & {
    options: ReadonlyArray<{ value: string; label: string }>;
  }) {
  const generated = useId();
  const id = givenId ?? generated;
  return (
    <FieldFrame id={id} label={label} hint={hint} error={error}>
      <select
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
        className={cn(controlClasses(error), className)}
        {...props}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </FieldFrame>
  );
}

export function Checkbox({
  label,
  hint,
  id: givenId,
  ...props
}: { label: string; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  const generated = useId();
  const id = givenId ?? generated;
  return (
    <div className="flex items-start gap-3">
      <input
        id={id}
        type="checkbox"
        className="mt-1 h-4 w-4 rounded border-line accent-brand-700"
        aria-describedby={hint ? `${id}-hint` : undefined}
        {...props}
      />
      <div>
        <label htmlFor={id} className="text-sm font-medium text-ink">
          {label}
        </label>
        {hint && (
          <p id={`${id}-hint`} className="text-xs text-muted">
            {hint}
          </p>
        )}
      </div>
    </div>
  );
}
