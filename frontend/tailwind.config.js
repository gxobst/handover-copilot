/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // High-contrast industrial palette utilities specified in _docs/design-system.md
        industrial: {
          downtime: {
            DEFAULT: '#92400e', // amber-800
            bg: '#fef3c7',     // amber-100
            border: '#fcd34d', // amber-300
          },
          quality: {
            DEFAULT: '#6b21a8', // purple-800
            bg: '#f3e8ff',     // purple-100
            border: '#d8b4fe', // purple-300
          },
          safety: {
            DEFAULT: '#991b1b', // red-800
            bg: '#fee2e2',     // red-100
            border: '#fca5a5', // red-300
          },
          info: {
            DEFAULT: '#1e293b', // slate-800
            bg: '#f1f5f9',     // slate-100
            border: '#cbd5e1', // slate-300
          },
        },
      },
    },
  },
  plugins: [],
}
