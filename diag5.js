const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: false, slowMo: 200 });
  const context = await browser.newContext({ storageState: 'scraper/den_session.json' });
  const page = await context.newPage();

  console.log('Step 0: navigating home...');
  await page.goto('https://app.pickleballden.com', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  console.log('Step 0 done.');

  console.log('Step 1: clicking Play...');
  await page.getByText(/^play$/i).click({ timeout: 8000 });
  console.log('Step 1 done.');
  await page.waitForTimeout(1000);

  console.log('Step 2: clicking Shootout...');
  await page.getByText(/^shootout$/i).click({ timeout: 8000 });
  console.log('Step 2 done.');
  await page.waitForTimeout(1000);

  console.log('Step 3: clicking List Shootouts...');
  await page.getByText(/^list shootouts$/i).click({ timeout: 8000 });
  console.log('Step 3 done.');
  await page.waitForTimeout(2000);

  const bodyText = await page.locator('body').innerText().catch(() => '');
  console.log('Landed on Club Play List:', bodyText.includes('Club Play List') || bodyText.includes('Group 1'));

  await page.screenshot({ path: 'output/diag5_result.png' });
  await browser.close();
})();
