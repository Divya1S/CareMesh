import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "ghost" | "destructive";

const styles: Record<Variant, string> = {
  primary:
    "bg-primary text-white hover:bg-primary-strong disabled:opacity-50",
  ghost:
    "border border-line bg-card text-ink hover:bg-primary-soft disabled:opacity-50",
  destructive:
    "bg-risk text-white hover:opacity-90 disabled:opacity-50",
};

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-control px-5 text-[0.9375rem] font-medium transition-colors duration-150 ease-out ${styles[variant]} ${className}`}
      {...props}
    />
  );
}
