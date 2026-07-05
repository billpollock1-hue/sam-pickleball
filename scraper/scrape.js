const { chromium } = require('playwright');
const fs = require('fs');
const readline = require('readline');

(async () => {
  let browser;
  let page;
  let rl;

  try {
    const SESSION_FILE = `${__dirname}/den_session.json`;
    const CONFIG_FILE  = `${__dirname}/den_config.json`;
    const hasSession   = fs.existsSync(SESSION_FILE);
    const config       = fs.existsSync(CONFIG_FILE)
      ? JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'))
      : {};

    const UNATTENDED = process.env.SCRAPE_UNATTENDED === '1';
    browser = await chromium.launch({ headless: UNATTENDED, slowMo: UNATTENDED ? 0 : 120 });
    const context = hasSession
      ? await browser.newContext({ storageState: SESSION_FILE })
      : await browser.newContext();
    page = await context.newPage();

    rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout
    });

    const ask = (question) =>
      new Promise((resolve) => rl.question(question, answer => resolve(answer.trim())));

    const waitForEnter = (message) => {
      if (UNATTENDED) {
        throw new Error(`Unattended run requires manual step but none is possible: ${message}`);
      }
      return new Promise((resolve) => {
        console.log(message);
        process.stdin.resume();
        process.stdin.once('data', () => resolve());
      });
    };

    const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
    const unique = (arr) => [...new Set(arr)];

    let clubPlayListUrl = '';

    function parseInputDate(mmddyy) {
      if (!/^\d{6}$/.test(mmddyy)) {
        throw new Error(`Invalid date format: ${mmddyy}. Use MMDDYY, e.g. 010125`);
      }
      const mm = parseInt(mmddyy.slice(0, 2), 10);
      const dd = parseInt(mmddyy.slice(2, 4), 10);
      const yy = parseInt(mmddyy.slice(4, 6), 10);
      return new Date(2000 + yy, mm - 1, dd, 0, 0, 0, 0);
    }

    function parseShootoutStarted(startedText) {
      return new Date(startedText);
    }

    function isWithinWindow(dateObj, startDate, endDate) {
      return dateObj >= startDate && dateObj <= endDate;
    }

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
      const cleanedCells = rawCells.map(x => x.trim());

      const shootouts = [];
      for (let i = 0; i < cleanedCells.length - 4; i++) {
        if (
          cleanedCells[i] === 'Group 1' &&
          cleanedCells[i + 1].includes(',') &&
          cleanedCells[i + 2] === 'Completed'
        ) {
          shootouts.push({
            name: cleanedCells[i],
            started: cleanedCells[i + 1],
            status: cleanedCells[i + 2],
            players: cleanedCells[i + 4] || ''
          });
        }
      }

      const deduped = [];
      const seen = new Set();
      for (const s of shootouts) {
        if (!seen.has(s.started)) {
          seen.add(s.started);
          deduped.push(s);
        }
      }
      return deduped;
    }

    async function getGridMetrics() {
      return await page.evaluate(() => {
        const grid = document.querySelector('vaadin-grid');
        if (!grid || !grid.shadowRoot) return null;
        const table = grid.shadowRoot.querySelector('#table');
        if (!table) return null;
        return {
          scrollTop: table.scrollTop || 0,
          scrollHeight: table.scrollHeight || 0,
          clientHeight: table.clientHeight || 0
        };
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
        return {
          scrollTop: table.scrollTop || 0,
          scrollHeight: table.scrollHeight || 0,
          clientHeight: table.clientHeight || 0
        };
      }, delta);
    }

    function summarizeVisibleDates(shootouts) {
      if (!shootouts.length) return { newest: null, oldest: null };
      const dates = shootouts.map(s => parseShootoutStarted(s.started)).sort((a, b) => b - a);
      return { newest: dates[0], oldest: dates[dates.length - 1] };
    }

    async function collectShootoutsByTrueGridScroll(startDate, endDate, maxPasses = 220) {
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

        console.log(
          `Pass ${pass}: scrollTop=${currentTop}, ` +
          `visibleNewest=${newest ? newest.toLocaleString() : 'n/a'}, ` +
          `visibleOldest=${oldest ? oldest.toLocaleString() : 'n/a'}, ` +
          `newInRange=${newCount}, totalInRange=${seen.size}`
        );

        // Stop only after we've definitely scrolled past the start date.
        if (oldest && oldest < startDate) {
          console.log('Oldest visible shootout is older than start date. Stopping collection.');
          break;
        }

        const metricsAfter = await bumpGridScroll(delta);
        await sleep(3000);

        const nextTop = metricsAfter?.scrollTop ?? currentTop;

        const oldestMs = oldest ? oldest.getTime() : null;
        const newestMs = newest ? newest.getTime() : null;

        const gridMoved = nextTop !== currentTop && nextTop !== lastScrollTop;
        const datesChanged = oldestMs !== lastOldestMs || newestMs !== lastNewestMs;

        // Only stale if the grid isn't moving AND the visible date band isn't changing.
        if (!gridMoved && !datesChanged) {
          stalePasses++;
          console.log(`No effective movement/date change on pass ${pass}. stalePasses=${stalePasses}`);
        } else {
          stalePasses = 0;
        }

        lastScrollTop = currentTop;
        lastOldestMs = oldestMs;
        lastNewestMs = newestMs;

        if (stalePasses >= 12) {
          console.log('Grid scrolling appears exhausted. Stopping collection.');
          break;
        }
      }

      return Array.from(seen.values()).sort(
        (a, b) => parseShootoutStarted(b.started) - parseShootoutStarted(a.started)
      );
    }

    async function reopenClubPlayList() {
      await page.goto(clubPlayListUrl, { waitUntil: 'domcontentloaded' });
      await waitForClubList();
    }

    async function findAndOpenShootout(startedText, preferredScrollTop) {
      const searchOffsets = [0, -500, 500, -1000, 1000, -1500, 1500, -2200, 2200];

      for (const offset of searchOffsets) {
        const targetTop = Math.max(0, preferredScrollTop + offset);
        await setGridScrollTop(targetTop);
        await sleep(2200);

        const locator = page.getByText(startedText, { exact: true }).first();
        if (await locator.count()) {
          try {
            await locator.scrollIntoViewIfNeeded();
            await sleep(500);
            await locator.click();
            await sleep(2200);
            return true;
          } catch {}
        }
      }

      return false;
    }

    async function clickViewScores() {
      const bodyText = await page.locator('body').innerText();
      if (!bodyText.includes('View Scores')) {
        throw new Error('View Scores not found after opening shootout row.');
      }
      await page.getByText('View Scores', { exact: true }).first().click();
      await sleep(2500);
    }

    async function clickAllScores() {
      const bodyText = await page.locator('body').innerText();
      if (bodyText.includes('All Scores')) {
        await page.getByText('All Scores', { exact: true }).first().click();
        await sleep(4000);
      }
    }

    function parseScoreCells(scoreCells) {
      const cleaned = scoreCells.map(x => x.trim()).filter(x => x !== '');

      let shootoutLabel = '';
      for (const item of cleaned) {
        if (item.startsWith('Shootout ')) {
          shootoutLabel = item;
          break;
        }
      }

      const ignoreHeaders = new Set([
        'Chevron icon',
        'Player Scores',
        'All Scores',
        'Find Player',
        'EXPORT',
        'COPY',
        'Posted',
        'Winning Team',
        'Score:',
        'Losing Team',
        'Type',
        'Pool'
      ]);

      const dataOnly = cleaned.filter(x => !ignoreHeaders.has(x) && x !== shootoutLabel);

      const rows = [];
      for (let j = 0; j + 6 < dataOnly.length; j += 7) {
        const chunk = dataOnly.slice(j, j + 7);
        if (!chunk[0].includes(',') || !chunk[6].startsWith('Pool ')) continue;

        rows.push({
          shootout: shootoutLabel,
          posted: chunk[0],
          winning_team: chunk[1],
          winning_score: chunk[2],
          losing_team: chunk[3],
          losing_score: chunk[4],
          game_type: chunk[5],
          pool: chunk[6]
        });
      }

      return rows;
    }

    async function extractCurrentScorePage() {
      const bodyText = await page.locator('body').innerText();
      if (!bodyText.includes('Player Scores')) {
        throw new Error('Player Scores page not detected.');
      }
      const scoreCells = await page.locator('vaadin-grid-cell-content').allTextContents();
      return parseScoreCells(scoreCells);
    }

    function getArg(name) {
      const idx = process.argv.indexOf(name);
      if (idx >= 0 && idx + 1 < process.argv.length) return process.argv[idx + 1];
      return null;
    }

    const startInput = getArg('--start') || await ask('Enter start date (MMDDYY), e.g. 010125: ');
    const endInput = getArg('--end') || await ask('Enter end date (MMDDYY), e.g. 040226: ');
    const outputArg = getArg('--output');

    const startDate = parseInputDate(startInput);
    const endDate = new Date(parseInputDate(endInput));
    endDate.setHours(23, 59, 59, 999);

    console.log(`Using date window: ${startDate.toDateString()} through ${endDate.toDateString()}`);

    // ── Load credentials if available ───────────────────────────────────
    const CREDS_FILE = `${__dirname}/den_credentials.json`;
    const creds = fs.existsSync(CREDS_FILE)
      ? JSON.parse(fs.readFileSync(CREDS_FILE, 'utf8'))
      : {};
    const hasCredentials = creds.email && creds.password;

    async function autoLogin() {
      console.log('Attempting auto-login...');
      await page.goto('https://app.pickleballden.com', { waitUntil: 'domcontentloaded' });
      await sleep(3000);

      // Screenshot for debugging if something goes wrong
      const screenshotPath = 'output/login_debug.png';

      try {
        // Vaadin apps use vaadin-text-field / vaadin-password-field with internal inputs
        // Try multiple selector strategies in order
        const emailSelectors = [
          'vaadin-text-field input',
          'vaadin-email-field input',
          'input[type="email"]',
          'input[name="email"]',
          'input[placeholder*="email" i]',
          'input[autocomplete*="email" i]',
          'input',  // fallback: first input on page
        ];

        let emailField = null;
        for (const sel of emailSelectors) {
          const loc = page.locator(sel).first();
          if (await loc.count() > 0) {
            emailField = loc;
            console.log(`Email field found with selector: ${sel}`);
            break;
          }
        }

        if (!emailField) {
          await page.screenshot({ path: screenshotPath });
          throw new Error(`Could not find email field. Screenshot saved to ${screenshotPath}`);
        }

        await emailField.click();
        await emailField.fill(creds.email);

        const passSelectors = [
          'vaadin-password-field input',
          'input[type="password"]',
          'input[name="password"]',
        ];

        let passField = null;
        for (const sel of passSelectors) {
          const loc = page.locator(sel).first();
          if (await loc.count() > 0) {
            passField = loc;
            console.log(`Password field found with selector: ${sel}`);
            break;
          }
        }

        if (!passField) {
          await page.screenshot({ path: screenshotPath });
          throw new Error(`Could not find password field. Screenshot saved to ${screenshotPath}`);
        }

        await passField.click();
        await passField.fill(creds.password);
        await sleep(500);

        // Submit — try button types then text match
        const submitSelectors = [
          'button[type="submit"]',
          'vaadin-button[theme*="primary"]',
          'vaadin-button',
        ];
        let submitted = false;
        for (const sel of submitSelectors) {
          const btns = page.locator(sel);
          const count = await btns.count();
          for (let i = 0; i < count; i++) {
            const txt = (await btns.nth(i).innerText().catch(() => '')).toLowerCase();
            if (/sign in|log in|login|submit|continue/.test(txt) || sel === 'button[type="submit"]') {
              await btns.nth(i).click();
              submitted = true;
              break;
            }
          }
          if (submitted) break;
        }

        if (!submitted) {
          // Last resort: press Enter on the password field
          await passField.press('Enter');
        }

        await sleep(5000);

        const bodyText = await page.locator('body').innerText().catch(() => '');
        if (!bodyText.includes('Club Play List') && !bodyText.includes('Shootout')) {
          await page.screenshot({ path: screenshotPath });
          throw new Error(`Auto-login failed — credentials may be wrong or page changed. Screenshot saved to ${screenshotPath}`);
        }
        console.log('Auto-login successful.');

      } catch (err) {
        await page.screenshot({ path: screenshotPath }).catch(() => {});
        throw err;
      }
    }

    async function autoNavigateToClubPlayList() {
      console.log('Attempting auto-navigation via Play → Shootout → List Shootouts...');

      // Find all "Play" buttons on club cards and try each one
      const playButtons = page.getByText('Play', { exact: true });
      const count = await playButtons.count();
      console.log(`Found ${count} Play button(s) on page.`);

      for (let i = 0; i < count; i++) {
        try {
          // Click the Play dropdown
          await playButtons.nth(i).click();
          await sleep(1000);

          // Click Shootout submenu item
          const shootoutItem = page.getByText('Shootout', { exact: true }).first();
          if (!await shootoutItem.count()) continue;
          await shootoutItem.click();
          await sleep(1000);

          // Click List Shootouts
          const listItem = page.getByText('List Shootouts', { exact: true }).first();
          if (!await listItem.count()) continue;
          await listItem.click();
          await sleep(3000);

          // Check if we landed on the right page
          const bodyText = await page.locator('body').innerText().catch(() => '');
          if (bodyText.includes('Club Play List') || bodyText.includes('Group 1')) {
            console.log('Auto-navigated to Club Play List.');
            return true;
          }

          // Wrong club — go back and try the next one
          await page.goBack({ waitUntil: 'domcontentloaded' });
          await sleep(2000);
        } catch {
          // If anything fails on this card, try the next
          await page.goto('https://app.pickleballden.com', { waitUntil: 'domcontentloaded' });
          await sleep(2000);
        }
      }

      console.log('Could not auto-navigate to Club Play List.');
      return false;
    }

    // ── Login & navigate to Club Play List ──────────────────────────────
    // Navigate to app and determine state
    const startUrl = (hasSession && config.clubPlayListUrl)
      ? config.clubPlayListUrl
      : 'https://app.pickleballden.com';

    await page.goto(startUrl, { waitUntil: 'domcontentloaded' });
    await sleep(3000);

    let bodyText = await page.locator('body').innerText().catch(() => '');
    const onClubPlayList = bodyText.includes('Club Play List') || bodyText.includes('Group 1');
    const isLoggedIn = onClubPlayList
      || bodyText.includes('Account')
      || bodyText.includes('Friends')
      || bodyText.includes('Timeline')
      || bodyText.includes('Shootout');

    if (onClubPlayList) {
      console.log('Already on Club Play List — proceeding.');
      clubPlayListUrl = page.url();
    } else if (isLoggedIn) {
      console.log('Logged in but not on Club Play List — auto-navigating via menu.');
      const autoNav = await autoNavigateToClubPlayList();
      if (!autoNav) {
        await waitForEnter('👉 Navigate to Club Play List and leave the shootout list visible, then press ENTER...');
        await waitForClubList();
      }
      clubPlayListUrl = page.url();
    } else {
      console.log('Not logged in — attempting auto-login.');
      if (hasCredentials) {
        await autoLogin();
      } else {
        await waitForEnter('👉 Log in to Pickleball Den in the opened browser, then press ENTER here in Terminal...');
      }
      const autoNav = await autoNavigateToClubPlayList();
      if (!autoNav) {
        await waitForEnter('👉 Navigate to Club Play List and leave the shootout list visible, then press ENTER...');
        await waitForClubList();
      }
      clubPlayListUrl = page.url();
    }

    // Save session and URL for next run
    await context.storageState({ path: SESSION_FILE });
    const updatedConfig = { ...config, clubPlayListUrl };
    fs.writeFileSync(CONFIG_FILE, JSON.stringify(updatedConfig, null, 2));
    console.log(`Session and URL saved (${SESSION_FILE}, ${CONFIG_FILE})`);
    console.log(`Club Play List URL: ${clubPlayListUrl}`);

    const allShootouts = await collectShootoutsByTrueGridScroll(startDate, endDate, 220);
    console.log(`Collected ${allShootouts.length} shootouts within date window.`);
    console.log(allShootouts);

    if (allShootouts.length === 0) {
      console.log('No shootouts found in the specified date window.');
      return;
    }

    const results = [];

    for (let i = 0; i < allShootouts.length; i++) {
      const s = allShootouts[i];
      console.log(
        `\n👉 Processing shootout ${i + 1} of ${allShootouts.length}: ` +
        `${s.started} (seenScrollTop=${s.seenScrollTop})`
      );

      try {
        await reopenClubPlayList();

        const opened = await findAndOpenShootout(s.started, s.seenScrollTop);
        if (!opened) {
          throw new Error(`Could not relocate shootout near scrollTop ${s.seenScrollTop}`);
        }

        await clickViewScores();
        await clickAllScores();

        const rows = await extractCurrentScorePage();
        console.log(`✅ Extracted ${rows.length} rows from ${s.started}`);
        results.push(...rows);

      } catch (err) {
        console.log(`⚠️ Failed on ${s.started}: ${err.message}`);
      }
    }

    const deduped = unique(results.map(r => JSON.stringify(r))).map(x => JSON.parse(x));

    const csvHeader = [
      'shootout',
      'posted',
      'winning_team',
      'winning_score',
      'losing_team',
      'losing_score',
      'game_type',
      'pool'
    ];

    const csvLines = [
      csvHeader.join(','),
      ...deduped.map(r =>
        [
          r.shootout,
          r.posted,
          r.winning_team,
          r.winning_score,
          r.losing_team,
          r.losing_score,
          r.game_type,
          r.pool
        ].map(value => `"${String(value).replace(/"/g, '""')}"`).join(',')
      )
    ];

    const outputFile = outputArg || `shootout_scores_${startInput}_${endInput}.csv`;
    fs.writeFileSync(outputFile, csvLines.join('\n'), 'utf8');

    console.log(`\n🎉 Done. Wrote ${deduped.length} rows to ${outputFile}`);

  } catch (err) {
    console.error('\n❌ Script failed:', err.message);
    try { if (rl) rl.close(); } catch {}
    try { if (browser) await browser.close(); } catch {}
    process.exit(1);
  } finally {
    try { if (rl) rl.close(); } catch {}
    try { if (browser) await browser.close(); } catch {}
  }
})();