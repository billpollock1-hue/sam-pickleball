const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: false, slowMo: 200 });
  const context = await browser.newContext({ storageState: 'scraper/den_session.json' });
  const page = await context.newPage();

  console.log('Step 0: navigating home...');
  await page.goto('https://app.pickleballden.com', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);

  console.log('Step 1: clicking Play button...');
  await page.getByRole('button', { name: 'play' }).click({ timeout: 8000 });
  console.log('Step 1 done.');
  await page.waitForTimeout(1000);

  console.log('Dumping all menuitem roles visible now...');
  const items = await page.getByRole('menuitem').allInnerTexts();
  console.log('Menu items:', JSON.stringify(items));

  await page.screenshot({ path: 'output/diag6_result.png' });
  await browser.close();
})();
