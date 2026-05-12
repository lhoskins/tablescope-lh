import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Tenant branding hooks — override via CSS variables per tenant.
        brand: {
          DEFAULT: "var(--brand-color, #2563eb)",
          fg: "var(--brand-foreground, #ffffff)",
        },
      },
    },
  },
  plugins: [],
};

export default config;
