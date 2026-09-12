/** Tailwind static build config: colors come from the canonical token file. */
const tokens = require('./static/design-tokens.json');
module.exports = {
  darkMode: 'class',
  content: ['./templates/**/*.html', './static/js/**/*.js'],
  theme: {
    extend: {
      colors: {
        burgundy: tokens.burgundy,
        matte: tokens.surfaces.matte,
        // Neutros canónicos (tokens surfaces.neutral): las utilidades
        // text-neutral-*/bg-neutral-*/border-neutral-* mapean a tokens.
        neutral: tokens.surfaces.neutral,
      },
    },
  },
  plugins: [],
}
