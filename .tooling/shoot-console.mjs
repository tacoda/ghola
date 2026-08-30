/**
 * Screenshot the iii console once per pipeline stage, for the docs.
 *
 * Holds ONE page open and shoots it each time the job's stage changes, because
 * the console is a live SPA: reloading per stage would lose the trace panel's
 * streamed state and photograph a colder page than an operator actually sees.
 *
 * Stage comes from the job record over the bus rather than from the DOM. The
 * console renders sessions, not stages, and scraping a stage out of rendered
 * text would be a second source of truth that disagrees with the record the
 * moment either changes.
 *
 *   node shoot-console.mjs <job-id> [outdir]
 */
import { execFile } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { promisify } from 'node:util';
import puppeteer from 'puppeteer';

const run = promisify(execFile);

const JOB = process.argv[2];
const OUT = process.argv[3] ?? 'docs/img/console';
const PORT = process.env.MGR_PORT ?? '49154';
const CONSOLE_URL = process.env.CONSOLE_URL ?? 'http://localhost:3133/';
const TERMINAL = new Set(['landed', 'closed', 'failed', 'waiting']);

if (!JOB) {
  console.error('usage: node shoot-console.mjs <job-id> [outdir]');
  process.exit(2);
}

async function stageOf(id) {
  // A failed poll is "unknown", not a crash: the engine restarting mid-run
  // should cost one frame rather than the whole sequence.
  try {
    const { stdout } = await run('iii', [
      'trigger', 'ghola::job', '--json', JSON.stringify({ id }), '--port', PORT,
    ]);
    const d = JSON.parse(stdout);
    return (d.job ?? d).stage ?? 'unknown';
  } catch {
    return 'unknown';
  }
}

await mkdir(OUT, { recursive: true });

const browser = await puppeteer.launch({ headless: 'new' });
const page = await browser.newPage();
await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 2 });
await page.goto(CONSOLE_URL, { waitUntil: 'networkidle2', timeout: 30000 });
await new Promise((r) => setTimeout(r, 2500));

let seen = null;
let frame = 0;
const shot = [];

for (let i = 0; i < 200; i++) {
  const stage = await stageOf(JOB);

  if (stage !== seen && stage !== 'unknown') {
    // Let the console catch up with the record before shooting: the stage
    // changes when the factory writes it, and the trace panel is a moment
    // behind by way of the engine.
    await new Promise((r) => setTimeout(r, 3000));
    const name = `${String(frame).padStart(2, '0')}-${stage}.png`;
    await page.screenshot({ path: `${OUT}/${name}` });
    console.log(`${new Date().toISOString().slice(11, 19)}  ${stage} -> ${name}`);
    shot.push({ stage, file: name });
    seen = stage;
    frame++;
  }

  if (TERMINAL.has(stage)) break;
  await new Promise((r) => setTimeout(r, 4000));
}

await browser.close();
console.log(`\n${shot.length} frames in ${OUT}`);
for (const s of shot) console.log(`  ${s.stage.padEnd(10)} ${s.file}`);
