/**
 * Screenshot the operator surface — `make` — once per command, for the docs.
 *
 * The console shots show what a job looks like while it runs. These show what
 * you actually type, and they are photographs of real output: every frame is
 * the stdout of the command named in its own title bar, run against this
 * checkout, not a mock-up written to look convincing.
 *
 * Only read-only targets are listed. A capture script that spends money the
 * first time someone regenerates the pictures is a trap.
 *
 *   node shoot-terminal.mjs [outdir]
 */
import { execFile } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { promisify } from 'node:util';
import puppeteer from 'puppeteer';

const run = promisify(execFile);

const OUT = process.argv[2] ?? 'docs/img/terminal';
const ROOT = new URL('..', import.meta.url).pathname;

const FRAMES = [
  { name: 'doctor', args: ['doctor'], title: 'what is missing, before a turn finds out' },
  { name: 'help', args: ['help'], title: 'the whole operator surface' },
  { name: 'config', args: ['config'], title: 'every setting, and where it came from' },
  { name: 'audit', args: ['audit'], title: 'the append-only record' },
];

// The home directory is in half of this output and in none of the argument.
const scrub = (s) => s
  .replace(/\x1B\[[0-9;]*[A-Za-z]/g, '')
  .replaceAll(process.env.HOME ?? '~~~none~~~', '~')
  .trimEnd();

const esc = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

function html(frame, body) {
  return `<!doctype html><meta charset="utf-8">
<style>
  * { box-sizing: border-box; margin: 0; }
  body { background: #0D0D0F; padding: 28px; font: 15px/1.55 "JetBrains Mono", ui-monospace, Menlo, monospace; }
  .win { background: #16161A; border: 1px solid #2a2a31; border-radius: 10px; overflow: hidden; width: 1000px; }
  .bar { display: flex; align-items: center; gap: 8px; padding: 10px 14px; background: #1d1d22; border-bottom: 1px solid #2a2a31; }
  .dot { width: 11px; height: 11px; border-radius: 50%; }
  .t { margin-left: 10px; color: #8A8A93; font-size: 13px; }
  pre { padding: 18px 20px 22px; color: #E8E6E3; white-space: pre; }
  .cmd { color: #F2A93B; }
  .cmd::before { content: "$ "; color: #8A8A93; }
</style>
<div class="win" id="win">
  <div class="bar">
    <span class="dot" style="background:#c9584f"></span>
    <span class="dot" style="background:#d9a441"></span>
    <span class="dot" style="background:#5c8a5c"></span>
    <span class="t">ghola — ${esc(frame.title)}</span>
  </div>
  <pre><span class="cmd">make ${esc(frame.args.join(' '))}</span>

${esc(body)}</pre>
</div>`;
}

await mkdir(OUT, { recursive: true });

const browser = await puppeteer.launch({ headless: 'new' });
const page = await browser.newPage();
await page.setViewport({ width: 1080, height: 800, deviceScaleFactor: 2 });

let frame = 0;
for (const f of FRAMES) {
  // `make doctor` exits non-zero when something is missing, and a picture of a
  // real failure is still a picture worth having.
  const { stdout, stderr } = await run('make', f.args, { cwd: ROOT, maxBuffer: 1 << 22 })
    .catch((e) => ({ stdout: e.stdout ?? '', stderr: e.stderr ?? String(e) }));

  await page.setContent(html(f, scrub(stdout || stderr)), { waitUntil: 'load' });
  const name = `${String(frame).padStart(2, '0')}-${f.name}.png`;
  await (await page.$('#win')).screenshot({ path: `${OUT}/${name}` });
  console.log(`  make ${f.args.join(' ')} -> ${name}`);
  frame++;
}

await browser.close();
console.log(`\n${frame} frames in ${OUT}`);
