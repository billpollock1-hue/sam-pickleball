// One-off (re-runnable) backfill: walks every shootout/pool already in
// master_history_raw.csv within a date range and pulls Den's "View Event"
// data for it -- First Choice per game and the official Round Robin Stats
// standings -- the same way scrape.js's daily pass does going forward.
//
// Deliberately NOT sharing code with scrape.js's grid-scrolling/navigation
// functions (collectShootoutsByTrueGridScroll, findAndOpenShootout, etc.):
// those are copied verbatim below rather than refactored into a shared
// module, so this one-off tool carries zero risk of touching the
// already-proven, daily-running production scraper.
//
// Writes two CSVs (overwritten after every shootout processed, so an
// interrupted run keeps whatever progress it made):
//   data/backfill_standings.csv -- same shape as pool_standings.csv
//   data/backfill_matches.csv  -- one row per game, with Den's own
//     (abbreviated) team names/scores plus which team (if any) had First
//     Choice. Deliberately NOT matched up to master_history_raw.csv rows
//     here -- engine/apply_backfill.py does that correlation (by pool +
//     chronological order + score-pair, same approach as
//     view_event_lib.js's correlateFirstChoice) against the full-name
//     rows already on file, and updates first_choice there in place.
//
// Already-covered (play_date, shootout, pool) keys -- from an existing
// data/pool_standings.csv -- are skipped, so re-running this after a
// partial run (once its results are applied) only picks up what's left.

const { chromium } = require('playwright');
const fs = require('fs');
const viewEventLib = require('./view_event_lib');

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const unique = (arr) => [...new Set(arr)];

function getArg(name) {
  const idx = process.argv.indexOf(name);
  if (idx >= 0 && idx + 1 < process.argv.length) return process.argv[idx + 1];
  return null;
}

function parseInputDate(mmddyy) {
  if (!/^\d{6}$/.test(mmddyy)) {
    throw new Error(`Invalid date format: ${mmddyy}. Use MMDDYY, e.g. 082426`);
  }
  const mm = parseInt(mmddyy.slice(0, 2), 10);
  const dd = parseInt(mmddyy.slice(2, 4), 10);
  const yy = parseInt(mmddyy.slice(4, 6), 10);
  return new Date(2000 + yy, mm - 1, dd, 0, 0, 0, 0);
}

// --- Minimal CSV reader, just enough for this file's own output shape
// (quoted fields, "" escaping commas within a value). Not a general CSV
// parser -- deliberately simple since we control exactly what wrote these
// files (pool_standings.csv / master_history_raw.csv, both from this
// codebase's own writers).
function readCsv(path) {
  if (!fs.existsSync(path)) return [];
  const text = fs.readFileSync(path, 'utf8');
  const lines = text.split(/\r?\n/).filter((l) => l.length > 0);
  if (lines.length === 0) return [];

  function parseLine(line) {
    const fields = [];
    let cur = '';
    let inQuotes = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (inQuotes) {
        if (ch === '"') {
          if (line[i + 1] === '"') { cur += '"'; i++; } else { inQuotes = false; }
        } else {
          cur += ch;
        }
      } else if (ch === '"') {
        inQuotes = true;
      } else if (ch === ',') {
        fields.push(cur);
        cur = '';
      } else {
        cur += ch;
      }
    }
    fields.push(cur);
    return fields;
  }

  const header = parseLine(lines[0]);
  return lines.slice(1).map((line) => {
    const fields = parseLine(line);
    const row = {};
    header.forEach((h, i) => { row[h] = fields[i] !== undefined ? fields[i] : ''; });
    return row;
  });
}

function toCsv(header, rows) {
  const lines = [header.join(',')];
  for (const r of rows) {
    lines.push(header.map((h) => `"${String(r[h] ?? '').replace(/"/g, '""')}"`).join(','));
  }
  return lines.join('\n');
}

function formatDuration(ms) {
  const totalSec = Math.max(0, Math.round(ms / 1000));
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h${String(m).padStart(2, '0')}m`;
  if (m > 0) return `${m}m${String(s).padStart(2, '0')}s`;
  return `${s}s`;
}

function renderProgressBar(done, total, width = 24) {
  const pct = total > 0 ? done / total : 0;
  const filled = Math.round(pct * width);
  const bar = '#'.repeat(filled) + '-'.repeat(Math.max(0, width - filled));
  return `[${bar}] ${done}/${total} (${Math.round(pct * 100)}%)`;
}

// Prints one progress line before starting work on a shootout: how far
// through the whole run we are, elapsed time, and a rough ETA based on the
// average pace so far -- so a multi-hour unattended run gives some sense
// of how much longer it'll take, not just a wall of per-pool log lines.
function printProgress(doneCount, total, runStart, label) {
  const elapsedMs = Date.now() - runStart;
  const avgMs = doneCount > 0 ? elapsedMs / doneCount : 0;
  const remainingMs = avgMs * Math.max(0, total - doneCount);
  const eta = doneCount > 0 ? ` | elapsed ${formatDuration(elapsedMs)} | ETA ~${formatDuration(remainingMs)}` : '';
  console.log(`\n${renderProgressBar(doneCount, total)}${eta} | now: ${label}`);
}

function normShootout(x) {
  const n = parseInt(parseFloat(x), 10);
  return Number.isFinite(n) ? String(n) : String(x).trim();
}

(async () => {
  let browser;
  try {
    const SESSION_FILE = `${__dirname}/den_session.json`;
    const CONFIG_FILE = `${__dirname}/den_config.json`;
    if (!fs.existsSync(SESSION_FILE) || !fs.existsSync(CONFIG_FILE)) {
      throw new Error('No saved session/config found. Run scraper/scrape.js once first (any small date range) to establish login.');
    }
    const config = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'));

    const startInput = getArg('--start');
    const endInput = getArg('--end');
    if (!startInput || !endInput) {
      throw new Error('Usage: node backfill_view_event.js --start MMDDYY --end MMDDYY');
    }
    const startDate = parseInputDate(startInput);
    const endDate = new Date(parseInputDate(endInput));
    endDate.setHours(23, 59, 59, 999);
    console.log(`Backfill window: ${startDate.toDateString()} through ${endDate.toDateString()}`);

    // Already-covered pools, so this is safe to re-run after applying a
    // partial result.
    const existingStandings = readCsv('data/pool_standings.csv');
    const covered = new Set(
      existingStandings.map((r) => `${r.play_date}|${normShootout(r.shootout)}|${r.pool}`)
    );
    console.log(`${covered.size / 4 | 0} pool(s) already covered in data/pool_standings.csv (skipping those).`);

    browser = await chromium.launch({ headless: false, slowMo: 60 });
    const context = await browser.newContext({ storageState: SESSION_FILE });
    const page = await context.newPage();

    // --- Copied verbatim from scrape.js (see header comment for why) ---
    async function waitForClubList() {
      await page.waitForLoadState('domcontentloaded');
      await sleep(3000);
      const bodyText = await page.locator('body').innerText();
      if (!bodyText.includes('Club Play List')) {
        throw new Error('Club Play List text not detected on page.');
      }
    }

    async function getVisibleShootouts() {
      const rawCells = await page.locator('vaadin-grid-cell-content').allTextContents();
      const cleanedCells = rawCells.map((x) => x.trim());
      const shootouts = [];
      for (let i = 0; i < cleanedCells.length - 4; i++) {
        if (cleanedCells[i] === 'Group 1' && cleanedCells[i + 1].includes(',') && cleanedCells[i + 2] === 'Completed') {
          shootouts.push({
            name: cleanedCells[i],
            started: cleanedCells[i + 1],
            status: cleanedCells[i + 2],
            players: cleanedCells[i + 4] || '',
          });
        }
      }
      const deduped = [];
      const seen = new Set();
      for (const s of shootouts) {
        if (!seen.has(s.started)) { seen.add(s.started); deduped.push(s); }
      }
      return deduped;
    }

    function parseShootoutStarted(startedText) { return new Date(startedText); }
    function isWithinWindow(d, s, e) { return d >= s && d <= e; }

    async function getGridMetrics() {
      return await page.evaluate(() => {
        const grid = document.querySelector('vaadin-grid');
        if (!grid || !grid.shadowRoot) return null;
        const table = grid.shadowRoot.querySelector('#table');
        if (!table) return null;
        return { scrollTop: table.scrollTop || 0, scrollHeight: table.scrollHeight || 0, clientHeight: table.clientHeight || 0 };
      });
    }
    async function setGridScrollTop(value) {
      await page.evaluate((scrollTop) => {
        const grid = document.querySelector('vaadin-grid');
        if (!grid || !grid.shadowRoot) return;
        const table = grid.shadowRoot.querySelector('#table');
        if (!table) return;
        table.scrollTop = scrollTop;
      }, value);
    }
    async function bumpGridScroll(delta) {
      return await page.evaluate((d) => {
        const grid = document.querySelector('vaadin-grid');
        if (!grid || !grid.shadowRoot) return null;
        const table = grid.shadowRoot.querySelector('#table');
        if (!table) return null;
        table.scrollTop = Math.max(0, (table.scrollTop || 0) + d);
        return { scrollTop: table.scrollTop || 0, scrollHeight: table.scrollHeight || 0, clientHeight: table.clientHeight || 0 };
      }, delta);
    }
    function summarizeVisibleDates(shootouts) {
      if (!shootouts.length) return { newest: null, oldest: null };
      const dates = shootouts.map((s) => parseShootoutStarted(s.started)).sort((a, b) => b - a);
      return { newest: dates[0], oldest: dates[dates.length - 1] };
    }

    async function collectShootoutsByTrueGridScroll(startDate, endDate, maxPasses = 600) {
      const seen = new Map();
      let stalePasses = 0;
      let lastScrollTop = -1;
      let lastOldestMs = null;
      let lastNewestMs = null;
      const delta = 700;

      await setGridScrollTop(0);
      await sleep(2500);

      for (let pass = 1; pass <= maxPasses; pass++) {
        const metricsBefore = await getGridMetrics();
        const currentTop = metricsBefore?.scrollTop ?? 0;
        const visible = await getVisibleShootouts();
        const { newest, oldest } = summarizeVisibleDates(visible);

        let newCount = 0;
        for (const s of visible) {
          const d = parseShootoutStarted(s.started);
          if (isWithinWindow(d, startDate, endDate) && !seen.has(s.started)) {
            seen.set(s.started, { ...s, seenScrollTop: currentTop });
            newCount++;
          }
        }

        console.log(`Pass ${pass}: scrollTop=${currentTop}, newest=${newest ? newest.toLocaleString() : 'n/a'}, oldest=${oldest ? oldest.toLocaleString() : 'n/a'}, newInRange=${newCount}, totalInRange=${seen.size}`);

        if (oldest && oldest < startDate) {
          console.log('Oldest visible shootout is older than start date. Stopping collection.');
          break;
        }

        const metricsAfter = await bumpGridScroll(delta);
        await sleep(1200);
        const nextTop = metricsAfter?.scrollTop ?? currentTop;
        const oldestMs = oldest ? oldest.getTime() : null;
        const newestMs = newest ? newest.getTime() : null;
        const gridMoved = nextTop !== currentTop && nextTop !== lastScrollTop;
        const datesChanged = oldestMs !== lastOldestMs || newestMs !== lastNewestMs;

        if (!gridMoved && !datesChanged) { stalePasses++; } else { stalePasses = 0; }
        lastScrollTop = currentTop; lastOldestMs = oldestMs; lastNewestMs = newestMs;
        if (stalePasses >= 12) { console.log('Grid scrolling appears exhausted. Stopping collection.'); break; }
      }
      return Array.from(seen.values()).sort((a, b) => parseShootoutStarted(b.started) - parseShootoutStarted(a.started));
    }

    async function reopenClubPlayList() {
      await page.goto(config.clubPlayListUrl, { waitUntil: 'domcontentloaded' });
      await waitForClubList();
    }

    async function findAndOpenShootout(startedText, preferredScrollTop) {
      const searchOffsets = [0, -500, 500, -1000, 1000, -1500, 1500, -2200, 2200];
      for (const offset of searchOffsets) {
        const targetTop = Math.max(0, preferredScrollTop + offset);
        await setGridScrollTop(targetTop);
        await sleep(1500);
        const locator = page.getByText(startedText, { exact: true }).first();
        if (await locator.count()) {
          try {
            await locator.scrollIntoViewIfNeeded();
            await sleep(400);
            await locator.click();
            await sleep(2000);
            return true;
          } catch {}
        }
      }
      return false;
    }
    // --- end copied section ---

    await reopenClubPlayList();
    const allShootouts = await collectShootoutsByTrueGridScroll(startDate, endDate);
    console.log(`Collected ${allShootouts.length} shootouts within date window.`);

    const shootoutsByDate = {};
    for (const s of allShootouts) {
      const dateKey = new Date(s.started).toDateString();
      if (!shootoutsByDate[dateKey]) shootoutsByDate[dateKey] = [];
      shootoutsByDate[dateKey].push(s);
    }
    for (const dateKey in shootoutsByDate) {
      shootoutsByDate[dateKey].sort((a, b) => new Date(a.started) - new Date(b.started));
      shootoutsByDate[dateKey].forEach((s, idx) => { s.sessionNumber = idx + 1; });
    }

    const standingsResults = [];
    const matchResults = [];

    function flush() {
      fs.writeFileSync(
        'data/backfill_standings.csv',
        toCsv(['play_date', 'shootout', 'pool', 'rank', 'player', 'wins', 'losses', 'diff'], standingsResults),
        'utf8'
      );
      fs.writeFileSync(
        'data/backfill_matches.csv',
        toCsv(
          ['play_date', 'shootout', 'pool', 'match_index', 'team1', 'team1_score', 'team2', 'team2_score', 'first_choice_team'],
          matchResults
        ),
        'utf8'
      );
    }

    const runStart = Date.now();
    for (let i = 0; i < allShootouts.length; i++) {
      const s = allShootouts[i];
      const playDate = new Date(s.started).toISOString().slice(0, 10);
      printProgress(i, allShootouts.length, runStart, `${playDate} session ${s.sessionNumber} (started ${s.started})`);

      try {
        await reopenClubPlayList();
        const opened = await findAndOpenShootout(s.started, s.seenScrollTop);
        if (!opened) { console.log('  ⚠ Could not relocate this shootout -- skipping.'); continue; }
        if (!await viewEventLib.openViewEventForOpenShootout(page)) {
          console.log('  ⚠ No View Event button -- skipping.');
          continue;
        }

        const pools = await viewEventLib.listPoolsInBracket(page);
        const poolsToDo = pools.filter((p) => !covered.has(`${playDate}|${s.sessionNumber}|${p}`));
        if (poolsToDo.length === 0) {
          console.log(`  (all ${pools.length} pool(s) already covered -- skipping)`);
          continue;
        }

        for (const poolName of poolsToDo) {
          const opened2 = await viewEventLib.openPoolMatches(page, poolName);
          if (!opened2) {
            console.log(`  ⚠ Could not open View Matches for ${poolName} -- skipping.`);
          } else {
            const { matches, standings } = await viewEventLib.extractMatchesAndStandings(page);
            standings.forEach((row) => {
              standingsResults.push({ play_date: playDate, shootout: s.sessionNumber, pool: poolName, ...row });
            });
            matches.forEach((m) => {
              const [t1, t2] = m.teams;
              matchResults.push({
                play_date: playDate,
                shootout: s.sessionNumber,
                pool: poolName,
                match_index: m.matchIndex,
                team1: (t1.names || []).join(' / '),
                team1_score: t1.score,
                team2: (t2.names || []).join(' / '),
                team2_score: t2.score,
                first_choice_team: t1.hasFirstChoice ? (t1.names || []).join(' / ') : (t2.hasFirstChoice ? (t2.names || []).join(' / ') : ''),
              });
            });
            const leader = standings.find((x) => x.rank === 1);
            console.log(`  ✅ ${poolName}: ${matches.length} match(es), ${standings.length} standings row(s)` + (leader ? ` (leader: ${leader.player})` : ''));
          }

          // Re-anchor for the next pool.
          await reopenClubPlayList();
          const reopened = await findAndOpenShootout(s.started, s.seenScrollTop);
          if (!reopened || !await viewEventLib.openViewEventForOpenShootout(page)) {
            console.log('  ⚠ Could not re-open View Event for the next pool -- moving to next shootout.');
            break;
          }
        }

        flush();
      } catch (err) {
        console.log(`  ⚠ Failed on this shootout: ${err.message}`);
      }
    }

    flush();
    printProgress(allShootouts.length, allShootouts.length, runStart, 'done');
    console.log(`\n🎉 Backfill pass done in ${formatDuration(Date.now() - runStart)}. ${standingsResults.length} standings row(s), ${matchResults.length} match row(s) written.`);
    console.log('Next: python3 engine/apply_backfill.py');
  } catch (err) {
    console.error('\n❌ Backfill failed:', err.message);
    process.exitCode = 1;
  } finally {
    try { if (browser) await browser.close(); } catch {}
  }
})();
