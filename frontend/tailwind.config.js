/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}", "./components/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#100904",
        accent: "#dc5000",
        mint: "#ffb829",
        // Warm greys so existing zinc utilities follow the darkroom palette.
        zinc: {
          100: "#ffedd7",
          200: "#f1dcc4",
          300: "#dcc8b1",
          400: "#b5a690",
          500: "#8a7b6b",
          600: "#6c5f51",
          700: "#40372e",
          800: "#2a1d14",
          900: "#1a0f08",
        },
        amber: "#fbbf24",
        rose: "#ff7a2f",
      },
      keyframes: {
        splashIn: {
          "0%": { opacity: "0", transform: "translateY(24px)", filter: "blur(8px)" },
          "100%": { opacity: "1", transform: "none", filter: "none" },
        },
        lane: { "0%": { transform: "translateX(-100%)" }, "100%": { transform: "translateX(300%)" } },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui"],
        display: ["var(--font-display)", "var(--font-sans)", "ui-sans-serif", "system-ui"],
        serif: ["var(--font-serif)", "Georgia", "serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
