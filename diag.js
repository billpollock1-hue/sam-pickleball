const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ storageState: 'scraper/den_session.json' });
  const page = await context.newPage();
  await page.goto('https://app.pickleballden.com', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(5000);

  const ua = await page.evaluate(() => navigator.userAgent);
  const webdriver = await page.evaluate(() => navigator.webdriver);
  console.log('User-Agent:', ua);
  console.log('navigator.webdriver:', webdriver);

  const exactCount = await page.getByText('Play', { exact: true }).count();
  console.log('Exact Play matches:', exactCount);

  const html = await page.evaluate(() => {
    const headings = Array.from(document.querySelectorAll('h2,h3,h1'));
    const target = headings.find(function(el) { return el.textContent.indexOf('AAZPC DEN 6AM') !== -1; });
    if (!target) return 'HEADING NOT FOUND';
    const card = target.closest('div');
    return card ? card.outerHTML : 'CARD PARENT NOT FOUND';
  });
  require('fs').writeFileSync('output/card_html_dump.txt', html);
  console.log('Dumped card HTML to output/card_html_dump.txt, length:', html.length);

  await browser.close();
})();
