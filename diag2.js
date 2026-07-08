const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ storageState: 'scraper/den_session.json' });
  const page = await context.newPage();
  await page.goto('https://app.pickleballden.com', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(5000);

  const a = await page.getByText(/^play$/i).count();
  console.log('A) getByText(/^play$/i):', a);

  const b = await page.locator('vaadin-button.pd-context-button').count();
  console.log('B) vaadin-button.pd-context-button (all):', b);

  const c = await page.locator('vaadin-button.pd-context-button').filter({ hasText: /^play$/i }).count();
  console.log('C) pd-context-button filtered by /^play$/i:', c);

  const texts = await page.locator('vaadin-button.pd-context-button').allInnerTexts();
  console.log('D) All pd-context-button innerTexts:', JSON.stringify(texts));

  await browser.close();
})();
