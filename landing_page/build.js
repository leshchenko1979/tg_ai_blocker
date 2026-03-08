const { execSync } = require('child_process');
const fs = require('fs-extra');
const crypto = require('crypto');
const path = require('path');

// Clean up old hashed CSS files
console.log('Cleaning up old CSS files...');
const distDir = path.join(__dirname, 'dist');
if (fs.existsSync(distDir)) {
  const files = fs.readdirSync(distDir);
  files.forEach(file => {
    if (file.startsWith('output.') && file.endsWith('.css') && file !== 'output.css') {
      fs.removeSync(path.join(distDir, file));
    }
  });
}

// Build CSS with Tailwind
console.log('Building CSS...');
execSync('tailwindcss build src/input.css -o dist/temp.css --content "src/**/*.{html,js}" --minify', { stdio: 'inherit' });

// Read the built CSS file
const cssContent = fs.readFileSync('dist/temp.css');
const cssHash = crypto.createHash('md5').update(cssContent).digest('hex').substring(0, 8);
const hashedCssFilename = `output.${cssHash}.css`;

// Rename CSS file with hash
fs.renameSync('dist/temp.css', `dist/${hashedCssFilename}`);

// Add cache control meta tags for HTML
const cacheControlMeta = `
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
`;

const htmlFiles = ['index.html', 'index-ru.html'];
for (const htmlFile of htmlFiles) {
  let htmlContent = fs.readFileSync(path.join('src', htmlFile), 'utf8');

  htmlContent = htmlContent.replace(
    /href="output\.css"/g,
    `href="${hashedCssFilename}"`
  );

  htmlContent = htmlContent.replace(
    /(<meta charset="UTF-8">)/,
    `$1${cacheControlMeta}`
  );

  fs.writeFileSync(path.join('dist', htmlFile), htmlContent);
}

// Copy assets folder if it exists
const srcAssetsDir = path.join(__dirname, 'src', 'assets');
const distAssetsDir = path.join(__dirname, 'dist', 'assets');
if (fs.existsSync(srcAssetsDir)) {
  console.log('Copying assets...');
  fs.copySync(srcAssetsDir, distAssetsDir);
}

// Create _headers file for GitHub Pages cache control
const headersContent = `/*
  Cache-Control: no-cache, no-store, must-revalidate
  Pragma: no-cache
  Expires: 0

*.css
  Cache-Control: public, max-age=31536000, immutable

*.js
  Cache-Control: public, max-age=31536000, immutable

*.png
  Cache-Control: public, max-age=31536000, immutable

*.jpg
  Cache-Control: public, max-age=31536000, immutable

*.svg
  Cache-Control: public, max-age=31536000, immutable
`;

fs.writeFileSync('dist/_headers', headersContent);

console.log(`Built successfully! CSS hash: ${cssHash}`);
console.log(`CSS file: ${hashedCssFilename}`);