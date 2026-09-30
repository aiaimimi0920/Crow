import fs from 'node:fs'

// The effective-line policy treats this local preview entrypoint as generated.
// Keep it reproducible in clean CI checkouts; never overwrite a local custom entry.
const entry = new URL('../index.html', import.meta.url)
if (!fs.existsSync(entry)) {
  fs.writeFileSync(entry, `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>你的房还值多少？</title>
    <link rel="stylesheet" href="/runtime-tailwind.css" />
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
`)
}
