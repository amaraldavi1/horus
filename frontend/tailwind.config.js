/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: {
          50: '#f8fafc',
          100: '#f1f5f9',
          200: '#e2e8f0',
          700: '#293548',
          800: '#1c2536',
          900: '#131a28',
          950: '#0b101b',
        },
      },
    },
  },
  plugins: [],
};
