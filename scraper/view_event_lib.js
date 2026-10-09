// Shared helpers for reading Den's "View Event" pages (per-pool Matches +
// Round Robin Stats). Kept separate from the View Scores flow in scrape.js
// because View Event is navigated per-pool, not per-shootout.
//
// DOM structure confirmed by hand on 2026-09-25 (today's 2nd shootout,
// Pool 1):
//   Club Play List row -> click -> "View Event" button -> Bracket List
//   (a vaadin-grid listing "Pool 1" / "Pool 2" ... / Status) -> click a
//   pool's name -> a vaadin-dialog-overlay opens with "View Teams" /
//   "View Matches" -> click "View Matches" -> the Matches page: a
//   "Round 1" section of <match-card> elements (ordinary DOM, NOT a
//   virtualized grid -- no stale-read risk like the Vaadin score grid),
//   each with two team rows (class mc-team-row).
//
//   Each team row has ONE action slot between the player names and the
//   score, which shows EITHER a winner checkmark (class
//   mc-team-item-winner, icon check.svg) OR a first-choice badge (class
//   mc-team-item-first-choice, icon first_choice.svg) -- never both
//   observed together in samples so far.
//
//   ** KNOWN CAVEAT (unverified either way as of this writing): if the
//   same team both won AND had first choice, Den's UI may only have room
//   to render the winner check, in which case FC would not be visible in
//   the DOM at all for that game. extractMatchesAndStandings() reports
//   hasFirstChoice strictly from what's actually in the DOM -- it never
//   guesses -- so a game where neither row shows the FC icon comes back
//   with no first-choice info, and callers should leave first_choice
//   blank rather than assume anything. **
//
//   Below the matches, a "Round Robin Stats" vaadin-grid (all-rows-visible
//   -- not virtualized) lists each of the pool's 4 players individually
//   with rank, Team(=player name), "W / L", and Diff -- this is Den's own
//   official pool finishing order, straight from the source.

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function openViewEventForOpenShootout(page) {
  const bodyText = await page.locator('body').innerText();
  if (!bodyText.includes('View Event')) return false;
  await page.getByText('View Event', { exact: true }).first().click();
  await sleep(2500);
  return true;
}

async function listPoolsInBracket(page) {
  const cells = (await page.locator('vaadin-grid-cell-content').allTextContents()).map((x) => x.trim());
  const pools = [];
  for (const c of cells) {
    if (/^Pool \d+$/.test(c)) pools.push(c);
  }
  return [...new Set(pools)];
}

async function openPoolMatches(page, poolName) {
  const poolLocator = page.getByText(poolName, { exact: true }).first();
  if (!(await poolLocator.count())) return false;
  await poolLocator.click();
  await sleep(1500);

  const viewMatchesBtn = page.locator('#viewMatches');
  if (await viewMatchesBtn.count()) {
    await viewMatchesBtn.click();
  } else {
    const byText = page.getByText('View Matches', { exact: true }).first();
    if (!(await byText.count())) return false;
    await byText.click();
  }
  await sleep(2500);

  const bodyText = await page.locator('body').innerText();
  return bodyText.includes('Round Robin Stats') || bodyText.includes('Matches');
}

// Returns { matches: [...], standings: [...] } for whichever pool's Matches
// page is currently open. Pure DOM read -- no clicking.
async function extractMatchesAndStandings(page) {
  return await page.evaluate(() => {
    function textOf(el) {
      return (el && el.textContent ? el.textContent : '').trim();
    }

    const matches = [];
    document.querySelectorAll('match-card').forEach((card, idx) => {
      const rows = card.querySelectorAll('.mc-team-row');
      const teams = [];
      rows.forEach((row) => {
        const names = Array.from(row.querySelectorAll('.mc-player-name')).map(textOf).filter(Boolean);
        const scoreEl = row.querySelector('.mc-team-item-score');
        const score = scoreEl ? parseInt(textOf(scoreEl), 10) : null;
        const isWinner = !!row.querySelector('.mc-team-item-winner');
        const hasFirstChoice = !!row.querySelector('.mc-team-item-first-choice');
        teams.push({ names, score, isWinner, hasFirstChoice });
      });
      if (teams.length === 2) {
        matches.push({ matchIndex: idx + 1, teams });
      }
    });

    const standings = [];
    const statsContainer = Array.from(document.querySelectorAll('vaadin-vertical-layout')).find(
      (el) => el.querySelector('h3') && el.querySelector('h3').textContent.trim() === 'Round Robin Stats'
    );
    if (statsContainer) {
      const cellTexts = Array.from(statsContainer.querySelectorAll('vaadin-grid-cell-content')).map(textOf);
      const withoutLabels = cellTexts.filter((t) => t !== 'Team' && t !== 'W / L' && t !== 'Diff');
      const dataOnly = withoutLabels.filter((t) => t !== '');
      for (let i = 0; i + 3 < dataOnly.length; i += 4) {
        const rank = dataOnly[i];
        const player = dataOnly[i + 1];
        const wl = dataOnly[i + 2];
        const diff = dataOnly[i + 3];
        if (!/^\d+$/.test(rank) || !/^\d+\s*\/\s*\d+$/.test(wl)) continue;
        const [wins, losses] = wl.split('/').map((s) => parseInt(s.trim(), 10));
        standings.push({ rank: parseInt(rank, 10), player, wins, losses, diff: parseInt(diff, 10) });
      }
    }

    return { matches, standings };
  });
}

// Given the View-Scores-derived rows for ONE pool (mutated in place) and the
// {matches} from extractMatchesAndStandings() for that same pool, attach a
// first_choice field to each row. Correlates by chronological order within
// the pool (posted timestamp <-> match order 1,2,3), then double-checks the
// score pair actually matches before trusting the pairing -- if it doesn't
// line up, that row is left alone rather than risking a wrong attribution.
function correlateFirstChoice(poolRows, matches) {
  const sortedRows = [...poolRows].sort((a, b) => new Date(a.posted) - new Date(b.posted));
  const sortedMatches = [...matches].sort((a, b) => a.matchIndex - b.matchIndex);
  const n = Math.min(sortedRows.length, sortedMatches.length);

  for (let i = 0; i < n; i++) {
    const row = sortedRows[i];
    const match = sortedMatches[i];
    const winScore = parseInt(row.winning_score, 10);
    const loseScore = parseInt(row.losing_score, 10);
    const matchScores = match.teams.map((t) => t.score).sort((a, b) => b - a);

    if (matchScores.length !== 2 || matchScores[0] !== winScore || matchScores[1] !== loseScore) {
      continue; // scores don't line up -- don't guess which game this is
    }

    const fcTeam = match.teams.find((t) => t.hasFirstChoice);
    if (!fcTeam) {
      row.first_choice = ''; // no FC badge visible on either row -- see caveat above
      continue;
    }
    row.first_choice = fcTeam.score === winScore ? row.winning_team : row.losing_team;
  }

  return sortedRows;
}

module.exports = {
  openViewEventForOpenShootout,
  listPoolsInBracket,
  openPoolMatches,
  extractMatchesAndStandings,
  correlateFirstChoice,
};
