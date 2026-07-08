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

  console.log('Step 2: clicking Shootout menuitem...');
  await page.getByRole('menuitem', { name: 'Shootout', exact: true }).click({ timeout: 8000 });
  console.log('Step 2 done.');
  await page.waitForTimeout(1000);

  console.log('Dumping menuitem roles visible now (should show List Shootouts etc)...');
  const items = await page.getByRole('menuitem').allInnerTexts();
  console.log('Menu items:', JSON.stringify(items));

  console.log('Step 3: clicking List Shootouts menuitem...');
  await page.getByRole('menuitem', { name: 'List Shootouts', exact: true }).click({ timeout: 8000 });
  console.log('Step 3 done.');
  await page.waitForTimeout(2000);

  const bodyText = await page.locator('body').innerText().catch(() => '');
  console.log('Landed on Club Play List:', bodyText.includes('Club Play List') || bodyText.includes('Group 1'));

  await page.screenshot({ path: 'output/diag7_result.png' });
  await browser.close();
})();
