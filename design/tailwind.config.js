// Same Tailwind setup the Stitch screens use (design/stitch/*.html), so their classes compile unchanged.
module.exports = {
  darkMode: "class",
  content: ["design/stitch/*.html", "postcrew/studio/static/*.js", "postcrew/studio/static/views/*.js",
            "postcrew/studio/static/index.html"],
  // tone classes are built from a name in the JS (bg-${tone}-50), which the scanner cannot see: keep the whole palette
  safelist: [{ pattern: /^(bg|text|border|ring)-(rose|orange|amber|blue|emerald|violet|sky|slate|teal|pink|indigo|red)-(50|100|200|300|400|500|600|700|800|900)$/,
               variants: ["hover"] }],
  theme: { extend: {
    borderRadius: { DEFAULT: "0.5rem", lg: "1rem", xl: "1.5rem", full: "9999px" },
    // one typeface everywhere, Helvetica-style (owner, 2026-11-16: "helvetica type professional font ... the same typography for the entire
    // postcrew"): Geist, then the Helvetica family where it is installed
    fontFamily: { headline: ["Geist", "Helvetica Neue", "Helvetica", "Arial", "sans-serif"], display: ["Geist", "Helvetica Neue", "Helvetica", "Arial", "sans-serif"],
                  body: ["Geist", "Helvetica Neue", "Helvetica", "Arial", "sans-serif"], label: ["Geist", "Helvetica Neue", "Helvetica", "Arial", "sans-serif"],
                  sans: ["Geist", "Helvetica Neue", "Helvetica", "Arial", "sans-serif"] },
  } },
  plugins: [require("@tailwindcss/forms"), require("@tailwindcss/container-queries")],
};
