/** Tailwind static build config: mirrors the palette of the removed CDN runtime config. */
module.exports = {
  darkMode: 'class',
  content: ['./templates/**/*.html', './static/js/**/*.js'],
  theme: {
    extend: {
      colors: {
        burgundy: {
          50: '#fdf2f4',
          100: '#fbe5e9',
          200: '#f7ccd5',
          300: '#f0a3b3',
          400: '#e56d88',
          500: '#d23d5f',
          600: '#9b1b30',
          700: '#800020',
          800: '#66001a',
          900: '#4d0013',
          950: '#2d020c',
        },
        matte: {
          900: '#121212',
          950: '#0a0a0a',
        },
      },
    },
  },
  plugins: [],
}
