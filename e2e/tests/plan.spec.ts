import { expect, test } from '@playwright/test'

test.describe('roll cutting planner', () => {
  test('creates a plan and shows per-roll cutting order, kerfs and leftover', async ({
    page,
  }) => {
    await page.goto('/')
    await page.getByTestId('roll-length').fill('1000')
    await page.getByTestId('kerf-width').fill('10')
    await page.getByTestId('segment-id-0').fill('A')
    await page.getByTestId('segment-length-0').fill('600')
    await page.getByTestId('segment-id-1').fill('B')
    await page.getByTestId('segment-length-1').fill('590')
    await page.getByTestId('segment-id-2').fill('C')
    await page.getByTestId('segment-length-2').fill('400')
    await page.getByTestId('submit-plan').click()

    // redirected to the persisted detail page
    await expect(page).toHaveURL(/\/plans\/\d+$/)
    await expect(page.getByText('第 1 卷')).toBeVisible()
    await expect(page.getByText('第 2 卷')).toBeVisible()
    await expect(page.getByText(/A（600 mm）/)).toBeVisible()
    await expect(page.getByText(/B（590 mm） → C（400 mm）/)).toBeVisible()
    await expect(page.getByText(/锯口 1 次/)).toBeVisible()
    await expect(page.getByText(/余料 0 mm/)).toBeVisible()
    await expect(page.getByText(/余料 400 mm/)).toBeVisible()

    // the plan is listed on the history page
    await page.goto('/plans')
    await expect(page.getByRole('link', { name: '查看' }).first()).toBeVisible()
  })

  test('422 errors are located on the form and the input is preserved', async ({
    page,
  }) => {
    await page.goto('/')
    // duplicate the id of the first row into the third row
    await page.getByTestId('segment-id-2').fill('S1')
    await page.getByTestId('submit-plan').click()

    await expect(page.getByRole('alert').first()).toBeVisible()
    await expect(page.getByText(/duplicate segment id/)).toBeVisible()
    // still on the form, original input preserved
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByTestId('segment-id-0')).toHaveValue('S1')
    await expect(page.getByTestId('segment-id-2')).toHaveValue('S1')
    await expect(page.getByTestId('segment-length-1')).toHaveValue('590')
  })

  test('segment longer than the roll is rejected with a located error', async ({
    page,
  }) => {
    await page.goto('/')
    await page.getByTestId('roll-length').fill('500')
    await page.getByTestId('segment-length-0').fill('600')
    await page.getByTestId('submit-plan').click()

    await expect(
      page.getByText('segment length 600 exceeds usable roll length 500'),
    ).toBeVisible()
    await expect(page.getByTestId('segment-length-0')).toHaveValue('600')
  })
})
