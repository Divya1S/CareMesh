import type { InputHTMLAttributes } from "react";

export function Field({
  label,
  error,
  id,
  className = "",
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string }) {
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-[0.875rem] font-medium text-ink">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : undefined}
        className="min-h-11 w-full rounded-control border border-line bg-card px-3.5 text-ink placeholder:text-ink-soft/60"
        {...props}
      />
      {error ? (
        <p id={`${id}-error`} className="mt-1.5 text-[0.8125rem] text-risk">
          {error}
        </p>
      ) : null}
    </div>
  );
}
