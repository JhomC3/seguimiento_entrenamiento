// Lighthouse CI config: 3 muestras bloqueadas contra el servidor loopback
// real (scripts/run_lighthouse.sh), reportes bajo .tmp (sandbox).
// CHROME_PATH se resuelve en run_lighthouse.sh al chromium de Playwright.
module.exports = {
  ci: {
    collect: {
      url: ['http://127.0.0.1:8765/'],
      numberOfRuns: 3,
      settings: {
        chromePath: process.env.CHROME_PATH,
        outputPath: '.tmp/lighthouse',
        preset: 'desktop',
        onlyCategories: ['performance', 'accessibility', 'best-practices', 'seo'],
      },
    },
    assert: {
      assertions: {
        'categories:performance': ['error', { minScore: 0.9 }],
        'categories:accessibility': ['error', { minScore: 0.9 }],
        'categories:best-practices': ['error', { minScore: 0.9 }],
        'categories:seo': ['error', { minScore: 0.9 }],
      },
    },
    upload: {
      target: 'filesystem',
      outputDir: '.tmp/lighthouse/reports',
    },
  },
};
