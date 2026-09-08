// Bundles src/index.ts into a single self-contained ESM file.
//
// Equivalent to
//   esbuild src/index.ts --bundle --platform=node --format=esm --target=node20
//           --outfile=dist/sidekick-channel.mjs --banner:js="#!/usr/bin/env node"
// plus a `require` shim on the second banner line: `ws` is CommonJS and calls
// `require('events')`, which an ESM bundle cannot serve without `createRequire`.
// The shim needs its own line under the shebang, and a newline does not survive
// package.json scripts on Windows, so the build lives here instead of the CLI.
import { build } from 'esbuild';

await build({
  entryPoints: ['src/index.ts'],
  bundle: true,
  platform: 'node',
  format: 'esm',
  target: 'node20',
  outfile: 'dist/sidekick-channel.mjs',
  banner: {
    js: [
      '#!/usr/bin/env node',
      "import { createRequire as __sidekickCreateRequire } from 'node:module';",
      'const require = __sidekickCreateRequire(import.meta.url);',
    ].join('\n'),
  },
  logLevel: 'info',
});
