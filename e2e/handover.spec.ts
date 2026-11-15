import { test, expect } from '@playwright/test';

// Generate unique shift dates for each test execution run to ensure
// clean, isolated database state across repeat runs against persistent storage.
const randomYear1 = 2030 + Math.floor(Math.random() * 60);
const randomMonth1 = String(Math.floor(Math.random() * 12) + 1).padStart(2, '0');
const randomDay1 = String(Math.floor(Math.random() * 28) + 1).padStart(2, '0');
const testDate = `${randomYear1}-${randomMonth1}-${randomDay1}`;
const testShiftKey = `${testDate}-early`;

const randomYear2 = 2100 + Math.floor(Math.random() * 60);
const randomMonth2 = String(Math.floor(Math.random() * 12) + 1).padStart(2, '0');
const randomDay2 = String(Math.floor(Math.random() * 28) + 1).padStart(2, '0');
const zeroEventsDate = `${randomYear2}-${randomMonth2}-${randomDay2}`;
const zeroEventsShiftKey = `${zeroEventsDate}-early`;

test.describe.serial('Shift Handover Copilot End-to-End Suite', () => {
  test.beforeAll(async ({ request }) => {
    // Ensure standard known models are configured before tests run
    await request.put('/api/admin/settings', {
      headers: {
        Authorization: 'Bearer dev-admin-secret-key-12345',
        'Content-Type': 'application/json',
      },
      data: {
        activeModel: 'google/gemini-3.5-flash-lite',
        fallbackModel: 'google/gemini-3.1-flash-lite',
      },
    });
  });

  test('Journey 1: Navigation & Initial Render', async ({ page }) => {
    // 1. Navigate to root /
    await page.goto('/');

    // 2. Header title & Industrial Plant Edition branding badge
    const headerTitle = page.locator('header h1');
    await expect(headerTitle).toBeVisible();
    await expect(headerTitle).toHaveText('Shift Handover Copilot');

    const brandingBadge = page.locator('header span:has-text("Industrial Plant Edition")');
    await expect(brandingBadge).toBeVisible();

    // 3. Active shift key badge format YYYY-MM-DD-(early|late|night)
    const shiftBadge = page.locator('[data-testid="shift-key-badge"]');
    await expect(shiftBadge).toBeVisible();
    await expect(shiftBadge).toHaveText(/^\d{4}-\d{2}-\d{2}-(early|late|night)$/);

    // 4. Changing shift selection updates badge and reloads shift-scoped data
    const nightShiftBtn = page.locator('button[role="radio"][aria-label="Night Shift"]');
    await nightShiftBtn.click();
    await expect(shiftBadge).toHaveText(/^\d{4}-\d{2}-\d{2}-night$/);

    const lateShiftBtn = page.locator('button[role="radio"][aria-label="Late Shift"]');
    await lateShiftBtn.click();
    await expect(shiftBadge).toHaveText(/^\d{4}-\d{2}-\d{2}-late$/);

    const earlyShiftBtn = page.locator('button[role="radio"][aria-label="Early Shift"]');
    await earlyShiftBtn.click();
    await expect(shiftBadge).toHaveText(/^\d{4}-\d{2}-\d{2}-early$/);

    // Step calendar day controls
    const nextDayBtn = page.locator('button[aria-label="Next Day"]');
    const prevBadgeText = await shiftBadge.innerText();
    await nextDayBtn.click();
    await expect(shiftBadge).not.toHaveText(prevBadgeText);
  });

  test('Journey 2: Event Logging & Real-Time Event List Updates', async ({ page }) => {
    await page.goto('/');

    // Navigate to our isolated test shift
    const dateInput = page.locator('#shift-date-input');
    await dateInput.fill(testDate);
    const earlyShiftBtn = page.locator('button[role="radio"][aria-label="Early Shift"]');
    await earlyShiftBtn.click();
    const shiftBadge = page.locator('[data-testid="shift-key-badge"]');
    await expect(shiftBadge).toHaveText(testShiftKey);

    // 1. Client-side validation: Empty submission is blocked without sending an API request
    let postRequestDispatched = false;
    const requestListener = (req: import('@playwright/test').Request) => {
      if (req.url().includes('/api/events') && req.method() === 'POST') {
        postRequestDispatched = true;
      }
    };
    page.on('request', requestListener);

    const submitBtn = page.locator('button[type="submit"]:has-text("Log Event")');
    await submitBtn.click();

    await expect(page.locator('#machine-error')).toBeVisible();
    await expect(page.locator('#machine-error')).toHaveText(/Machine name is required/i);
    await expect(page.locator('#note-error')).toBeVisible();
    await expect(page.locator('#note-error')).toHaveText(/Note is required/i);
    expect(postRequestDispatched).toBe(false);

    page.off('request', requestListener);

    // 2. Valid event logging: Press-01, downtime, Hydraulic pressure drop on valve 3
    await page.locator('#machine').fill('Press-01');
    const downtimeRadio = page.locator('button[role="radio"][aria-label="Downtime"]');
    await downtimeRadio.click();
    await page.locator('#note').fill('Hydraulic pressure drop on valve 3');
    await submitBtn.click();

    // Verify inputs are cleared
    await expect(page.locator('#machine')).toHaveValue('');
    await expect(page.locator('#note')).toHaveValue('');

    // Transient success message
    const successBanner = page.locator('div[role="status"]:has-text("Event logged successfully")');
    await expect(successBanner).toBeVisible();

    // Verify event appears in shift events table with downtime styling
    const eventsTable = page.locator('table[aria-label="Shift events"]');
    await expect(eventsTable).toBeVisible();

    const downtimeRow = eventsTable.locator('tbody tr').filter({ hasText: 'Hydraulic pressure drop on valve 3' });
    await expect(downtimeRow).toBeVisible();
    await expect(downtimeRow).toContainText('Press-01');

    const downtimeCategoryBadge = downtimeRow.locator('span:has-text("downtime")');
    await expect(downtimeCategoryBadge).toBeVisible();
    await expect(downtimeCategoryBadge).toHaveClass(/bg-amber-100/);
    await expect(downtimeCategoryBadge).toHaveClass(/text-amber-800/);

    // 3. Safety-critical event logging: Press-01, safety, Spill containment deployed
    await page.locator('#machine').fill('Press-01');
    const safetyRadio = page.locator('button[role="radio"][aria-label="Safety"]');
    await safetyRadio.click();
    await page.locator('#note').fill('Spill containment deployed');
    await submitBtn.click();

    await expect(page.locator('#machine')).toHaveValue('');
    await expect(page.locator('#note')).toHaveValue('');

    const safetyRow = eventsTable.locator('tbody tr').filter({ hasText: 'Spill containment deployed' });
    await expect(safetyRow).toBeVisible();
    await expect(safetyRow).toContainText('Press-01');

    const safetyCategoryBadge = safetyRow.locator('span:has-text("safety")');
    await expect(safetyCategoryBadge).toBeVisible();
    await expect(safetyCategoryBadge).toHaveClass(/bg-red-100/);
    await expect(safetyCategoryBadge).toHaveClass(/text-red-800/);
    await expect(safetyCategoryBadge).toHaveClass(/font-semibold/);

    // Verify total events logged in table
    const rows = eventsTable.locator('tbody tr');
    await expect(rows).toHaveCount(2);
  });

  test('Journey 3: Handover Report Generation & Content Rendering', async ({ page }) => {
    await page.goto('/');

    // 1. Zero-events validation: Generate button disabled with helper message
    const dateInput = page.locator('#shift-date-input');
    await dateInput.fill(zeroEventsDate);
    const earlyShiftBtn = page.locator('button[role="radio"][aria-label="Early Shift"]');
    await earlyShiftBtn.click();

    const zeroShiftBadge = page.locator('[data-testid="shift-key-badge"]');
    await expect(zeroShiftBadge).toHaveText(zeroEventsShiftKey);

    const genButton = page.locator('button:has-text("Generate Handover"), button:has-text("Regenerate Handover")');
    await expect(genButton).toBeDisabled();

    const zeroEventsHelper = page.locator('#generate-zero-events-helper');
    await expect(zeroEventsHelper).toBeVisible();
    await expect(zeroEventsHelper).toContainText('At least 1 shift event is required to generate a handover report.');

    // 2. Switch back to shift with logged events
    await dateInput.fill(testDate);
    await earlyShiftBtn.click();
    const shiftBadge = page.locator('[data-testid="shift-key-badge"]');
    await expect(shiftBadge).toHaveText(testShiftKey);

    await expect(genButton).toBeEnabled();

    // 3. Click "Generate Handover" and verify loading state
    await genButton.click();

    // Verify in-flight loading state or spinner
    const loadingOrReport = page.locator('button:has-text("Generating Handover..."), [data-testid="report-view"]');
    await expect(loadingOrReport.first()).toBeVisible();

    // 4. Report View rendered
    const reportView = page.locator('[data-testid="report-view"]');
    await expect(reportView).toBeVisible({ timeout: 20000 });

    // 5. Metadata bar
    const metadataBar = page.locator('[data-testid="report-metadata-bar"]');
    await expect(metadataBar).toBeVisible();
    await expect(metadataBar).toContainText('Version 1');
    await expect(metadataBar).toContainText(testShiftKey);
    await expect(metadataBar).toContainText('2 events synthesized');

    // 6. Executive Summary section
    const summarySection = page.locator('section[aria-labelledby="executive-summary-heading"]');
    await expect(summarySection).toBeVisible();
    await expect(summarySection.locator('h2')).toHaveText('Executive Summary');
    const summaryText = await summarySection.locator('div.text-sm').innerText();
    expect(summaryText.trim().length).toBeGreaterThan(0);

    // 7. Safety Notes section (spill was logged -> hazard flagged)
    const safetySection = page.locator('section[aria-labelledby="safety-notes-heading"]');
    await expect(safetySection).toBeVisible();
    await expect(safetySection.locator('h2')).toHaveText('Safety Notes');
    await expect(safetySection).toBeVisible();

    // 8. Open Actions section
    const actionsSection = page.locator('section[aria-labelledby="open-actions-heading"]');
    await expect(actionsSection).toBeVisible();
    await expect(actionsSection.locator('h2')).toHaveText('Open Actions');

    const actionsTable = actionsSection.locator('table');
    await expect(actionsTable).toBeVisible();
    const actionRows = actionsTable.locator('tbody tr');
    await expect(actionRows.first()).toBeVisible();

    // Check columns: Priority badge, action description, assigned owner
    const firstRowPriority = actionRows.first().locator('td').nth(0);
    await expect(firstRowPriority).toHaveText(/high|medium|low/i);

    const firstRowOwner = actionRows.first().locator('td').nth(2);
    const ownerText = await firstRowOwner.innerText();
    expect(ownerText.trim().length).toBeGreaterThan(0);
  });

  test('Journey 4: Report History Navigation & Version Inspection', async ({ page }) => {
    await page.goto('/');

    // Switch to test shift
    const dateInput = page.locator('#shift-date-input');
    await dateInput.fill(testDate);
    const earlyShiftBtn = page.locator('button[role="radio"][aria-label="Early Shift"]');
    await earlyShiftBtn.click();
    const shiftBadge = page.locator('[data-testid="shift-key-badge"]');
    await expect(shiftBadge).toHaveText(testShiftKey);

    // 1. Click "Report History" navigation tab
    const historyTab = page.locator('button:has-text("Report History")');
    await historyTab.click();

    // 2. Verify report history list displays Version 1 with timestamp
    const historyList = page.locator('[role="list"][aria-label="Report version history"]');
    await expect(historyList).toBeVisible();

    const versionItems = historyList.locator('[role="listitem"]');
    await expect(versionItems).toHaveCount(1);
    await expect(versionItems.first()).toContainText('v1');
    await expect(versionItems.first()).toContainText(testShiftKey);

    // 3. Click report entry in history list to inspect snapshot
    await versionItems.first().locator('button').click();
    await expect(page.locator('h2:has-text("Executive Summary"), h3:has-text("Executive Summary")').first()).toBeVisible();

    // 4. Return to Shift Board to generate subsequent report (version 2)
    const boardTab = page.locator('button:has-text("Shift Board")');
    await boardTab.click();

    const regenButton = page.locator('button:has-text("Regenerate Handover")');
    await expect(regenButton).toBeVisible();
    await regenButton.click();

    // Wait for version 2 to render
    const metadataBar = page.locator('[data-testid="report-metadata-bar"]');
    await expect(metadataBar).toContainText('Version 2', { timeout: 20000 });

    // 5. Navigate back to Report History tab and verify both versions
    await historyTab.click();
    await expect(historyList).toBeVisible();

    const updatedVersionItems = historyList.locator('[role="listitem"]');
    await expect(updatedVersionItems).toHaveCount(2);

    // Version 2 should be first (latest) and Version 1 second
    await expect(updatedVersionItems.nth(0)).toContainText('v2');
    await expect(updatedVersionItems.nth(0)).toContainText('Latest');
    await expect(updatedVersionItems.nth(1)).toContainText('v1');

    // Both versions remain selectable and verifiable
    await updatedVersionItems.nth(1).locator('button').click();
    await expect(page.locator('[data-testid="historical-version-banner"]')).toBeVisible();
    await expect(page.locator('[data-testid="historical-version-banner"]')).toContainText('Historical Version 1 Snapshot');
  });

  test('Journey 5: Admin & Model Settings View', async ({ page }) => {
    await page.goto('/');

    // 1. Open Admin Settings modal from header
    const adminTrigger = page.locator('button:has-text("Admin Settings")');
    await adminTrigger.click();

    const adminDialog = page.locator('[role="dialog"]');
    await expect(adminDialog).toBeVisible();
    await expect(adminDialog.locator('#admin-panel-title')).toHaveText('Admin Configuration Panel');

    // 2. Submit invalid token -> RFC 9457 error banner (401 Unauthorized), keeps panel locked
    const tokenInput = adminDialog.locator('#admin-token-input');
    await tokenInput.fill('invalid-token-secret-xyz');
    const unlockBtn = adminDialog.locator('button:has-text("Unlock")');
    await unlockBtn.click();

    const errorAlert = adminDialog.locator('div[role="alert"]');
    await expect(errorAlert).toBeVisible();
    await expect(errorAlert).toContainText(/Unauthorized|401|Invalid or missing admin token/i);

    // Panel remains locked
    await expect(tokenInput).toBeVisible();

    // 3. Enter valid admin token dev-admin-secret-key-12345
    await tokenInput.fill('dev-admin-secret-key-12345');
    await unlockBtn.click();

    // Unlocks panel and shows "Authenticated as Admin"
    await expect(adminDialog.locator('text=Authenticated as Admin')).toBeVisible();

    // Displays Active Model and Fallback Model cards
    await expect(adminDialog.locator('text=Active Model').first()).toBeVisible();
    await expect(adminDialog.locator('text=Fallback Model').first()).toBeVisible();

    // 4. Invalid model identifier validation error
    const activeModelInput = adminDialog.locator('#active-model-input');
    await activeModelInput.fill('invalid model identifier with spaces!');

    const validationAlert = adminDialog.locator('p[role="alert"]');
    await expect(validationAlert).toBeVisible();
    await expect(validationAlert).toContainText(/Model name contains invalid characters/i);

    const saveBtn = adminDialog.locator('button:has-text("Save Changes")');
    await expect(saveBtn).toBeDisabled();

    // 5. Update setting with valid model name and save
    await activeModelInput.fill('google/gemini-3.5-flash');
    await expect(saveBtn).toBeEnabled();
    await saveBtn.click();

    const successMessage = adminDialog.locator('div[role="status"]:has-text("Model settings updated successfully")');
    await expect(successMessage).toBeVisible();

    // Revert to default model to leave clean state
    await activeModelInput.fill('google/gemini-3.5-flash-lite');
    await saveBtn.click();
    await expect(adminDialog.locator('div[role="status"]:has-text("Model settings updated successfully")')).toBeVisible();

    // Close admin modal
    const closeBtn = adminDialog.locator('button[aria-label="Close admin panel"]');
    await closeBtn.click();
    await expect(adminDialog).not.toBeVisible();
  });
});
