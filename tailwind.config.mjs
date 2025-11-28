/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}'],
  theme: {
    extend: {
      colors: {
        // HKU Inspired Palette
        'brand-red': '#F2463A', // Pantone Warm Red U 2X
        'brand-yellow': '#FFD200', // Pantone Yellow U
        'brand-green': '#00B08B', // Pantone 346 U (The teal/green)
        'brand-blue': '#009CDE', // Pantone 2925 U
        'brand-dark': '#231F20', // Process Black U
        'brand-brown': '#4E3629', // Pantone Black 5U
        // Functional aliases
        'brand-primary': '#00B08B', // Using the Green as primary
        'brand-accent': '#009CDE', // Using Blue as accent
      },
      fontFamily: {
        // Clean, modern font stack for education
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
};
