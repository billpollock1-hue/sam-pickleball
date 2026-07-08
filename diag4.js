const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ storageState: 'scraper/den_session.json' });
  const page = await context.newPage();
  await page.goto('https://app.pickleballden.com', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);

  await page.getByText(/^play$/i).click();
  await page.waitForTimeout(1000);

  await page.getByText(/^shootout$/i).click();
  await page.waitForTimeout(1000);

  // Retry the "List Shootouts" click, since manual testing showed it can silently fail once
  let landed = false;
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.getByText(/^list shootouts$/i).click();
    await page.waitForTimeout(2000);
    const bodyText = await page.locator('body').innerText().catch(() => '');
    if (bodyText.includes('Club Play List') || bodyText.includes('Group 1')) {
      landed = true;
      console.log(`Landed on Club Play List after attempt ${attempt + 1}`);
      break;
    }
    console.log(`Attempt ${attempt + 1}: not yet on Club Play List, retrying...`);
  }

  console.log('Final result — landed on Club Play List:', landed);
  await page.screenshot({ path: 'output/diag4_result.png' });
  await browser.close();
})();
