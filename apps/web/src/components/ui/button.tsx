import type { ButtonHTMLAttributes } from "react";

/** Customised shadcn-style primitive: variant-driven, token-based, no extra deps. */
type Variant = "primary" | "secondary" | "ghost" | "danger";

const styles: Record<Variant, string> = {
  primary:
    "bg-accent text-[#14110c] font-semibold hover:bg-[#ff8a70] disabled:opacity-40 disabled:pointer-events-none",
  secondary:
    "bg-raised text-foreground border border-border hover:border-muted disabled:opacity-40 disabled:pointer-events-none",
  ghost: "text-muted hover:text-foreground disabled:opacity-40 disabled:pointer-events-none",
  danger:
    "bg-transparent text-danger border border-danger/50 hover:bg-danger/10 disabled:opacity-40 disabled:pointer-events-none",
};

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-accent ${styles[variant]} ${className}`}
      {...props}
    />
  );
}
