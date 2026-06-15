import { forwardRef } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";

const button = cva(
  "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-100",
  {
    variants: {
      variant: {
        primary: "bg-brand text-brand-fg hover:bg-brand-700",
        secondary:
          "border border-line-secondary bg-bg-primary text-ink-primary hover:bg-bg-secondary",
        ghost: "text-ink-secondary hover:bg-bg-secondary hover:text-ink-primary",
        brandSoft:
          "border border-brand-500 bg-brand-50 text-brand-700 hover:bg-brand-100",
        danger: "bg-danger text-white hover:opacity-90",
      },
      size: {
        sm: "h-7 px-2.5 text-[12px]",
        md: "h-8 px-3 text-[13px]",
        icon: "h-8 w-8",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(button({ variant, size }), className)}
      {...props}
    />
  ),
);
Button.displayName = "Button";
