import type { Config } from "tailwindcss";
import containerQueries from "@tailwindcss/container-queries";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      screens: {
        xs: "480px",
      },
      colors: {
        bg: {
          primary: "var(--bg-primary)",
          secondary: "var(--bg-secondary)",
          tertiary: "var(--bg-tertiary)",
        },
        ink: {
          primary: "var(--text-primary)",
          secondary: "var(--text-secondary)",
          tertiary: "var(--text-tertiary)",
        },
        line: {
          primary: "var(--border-primary)",
          secondary: "var(--border-secondary)",
          tertiary: "var(--border-tertiary)",
        },
        // Tenant branding hooks — override via CSS variables per tenant.
        brand: {
          DEFAULT: "var(--brand-color, #185fa5)",
          fg: "var(--brand-foreground, #ffffff)",
          50: "var(--brand-50)",
          100: "var(--brand-100)",
          500: "var(--brand-500)",
          700: "var(--brand-700)",
        },
        ai: {
          DEFAULT: "var(--color-ai)",
          bg: "var(--color-ai-bg)",
        },
        success: {
          DEFAULT: "var(--color-success)",
          bg: "var(--color-success-bg)",
        },
        warning: {
          DEFAULT: "var(--color-warning)",
          bg: "var(--color-warning-bg)",
        },
        danger: {
          DEFAULT: "var(--color-danger)",
          bg: "var(--color-danger-bg)",
        },
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        xl: "var(--radius-xl)",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "ui-sans-serif", "system-ui", "sans-serif"],
        code: ["JetBrains Mono", "Consolas", "SF Mono", "Menlo", "monospace"],
      },
      maxWidth: {
        content: "1280px",
      },
      width: {
        sidebar: "220px",
        rail: "272px",
      },
      height: {
        topbar: "64px",
      },
      spacing: {
        "safe-top": "env(safe-area-inset-top)",
        "safe-bottom": "env(safe-area-inset-bottom)",
        "safe-left": "env(safe-area-inset-left)",
        "safe-right": "env(safe-area-inset-right)",
      },
      minWidth: {
        touch: "44px",
      },
      minHeight: {
        touch: "44px",
      },
    },
  },
  plugins: [containerQueries],
};

export default config;
