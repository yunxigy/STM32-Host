// Isolated real TCP/HTTP tests + state machine + mini-program Page logic.
import { spawn } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
const roots = [new URL('./tests/', import.meta.url), new URL('../xcx/tests/', import.meta.url)];
const files = roots.flatMap(root => {
  if (!existsSync(root)) {
    console.warn(`SKIP external mini-program suite: ${fileURLToPath(root)} is not part of this repository`);
    return [];
  }
  return readdirSync(root).filter(name => /\.test\.(mjs|cjs)$/.test(name)).map(name => fileURLToPath(new URL(name, root)));
});
const child = spawn(process.execPath, ['--test', ...files], { stdio: 'inherit' });
child.on('exit', code => { process.exitCode = code ?? 1; });
child.on('error', error => { console.error(error); process.exitCode = 1; });
