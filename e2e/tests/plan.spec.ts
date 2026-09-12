import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

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

  test.describe('adjusting from an existing plan', () => {
    async function createOriginal(page: Page) {
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
      await expect(page).toHaveURL(/\/plans\/\d+$/)
      const id = Number(page.url().split('/').pop())
      return id
    }

    test('carries inputs into a new editable plan, keeps the original intact, and links both ways', async ({
      page,
    }) => {
      const originalId = await createOriginal(page)

      // start the adjustment from the read-only detail
      await page.getByTestId('adjust-from-plan').click()
      await expect(page).toHaveURL(`/?from=${originalId}`)
      await expect(page.getByTestId('source-banner')).toBeVisible()
      await expect(page.getByTestId('roll-length')).toHaveValue('1000')
      await expect(page.getByTestId('kerf-width')).toHaveValue('10')
      await expect(page.getByTestId('segment-id-0')).toHaveValue('A')
      await expect(page.getByTestId('segment-length-2')).toHaveValue('400')

      // change one segment length and re-solve under the existing rules
      await page.getByTestId('segment-length-1').fill('380')
      await page.getByTestId('submit-plan').click()
      await expect(page).toHaveURL(/\/plans\/\d+$/)
      const adjustedId = Number(page.url().split('/').pop())
      expect(adjustedId).not.toBe(originalId)

      // the new plan shows the "源自方案" link and the edited result
      const sourceLine = page.getByTestId('source-line')
      await expect(sourceLine).toBeVisible()
      await expect(sourceLine.getByRole('link', { name: `#${originalId}` })).toHaveAttribute(
        'href',
        `/plans/${originalId}`,
      )
      // roll 2 now holds 380+400+10 = 790, leftover 210; total leftover 610
      await expect(page.getByText(/余料 210 mm/)).toBeVisible()
      await expect(page.getByText(/余料 400 mm/)).toBeVisible()

      // follow the source link back: the original plan is untouched/read-only
      await sourceLine.getByRole('link').click()
      await expect(page).toHaveURL(`/plans/${originalId}`)
      await expect(page.getByText(/B（590 mm） → C（400 mm）/)).toBeVisible()
      await expect(page.getByText(/余料 0 mm/)).toBeVisible()
      await expect(page.getByTestId('source-line')).toHaveCount(0)

      // history list carries provenance for the adjustment only
      await page.goto('/plans')
      await expect(page.getByTestId(`source-link-${adjustedId}`)).toHaveAttribute(
        'href',
        `/plans/${originalId}`,
      )
      await expect(page.getByTestId(`source-link-${originalId}`)).toHaveCount(0)
    })

    test('ordinary creation shows no provenance banner', async ({ page }) => {
      await page.goto('/')
      await expect(page.getByTestId('source-banner')).toHaveCount(0)
    })

    test('an invalid source id on load reports the failure without trapping the user', async ({
      page,
    }) => {
      await page.goto('/?from=999999')
      await expect(page.getByTestId('from-load-error')).toBeVisible()
      await expect(page.getByRole('link', { name: '返回历史方案重新选择' })).toHaveAttribute(
        'href',
        '/plans',
      )
    })

    test('a rejected source on submit preserves every edit and lets the foreman re-pick the source', async ({
      page,
    }) => {
      const originalId = await createOriginal(page)
      await page.goto(`/?from=${originalId}`)
      await expect(page.getByTestId('source-banner')).toBeVisible()

      // the foreman edits before submitting; simulate the server rejecting
      // the provenance link once (e.g. source deleted between load and save)
      let rejectedOnce = false
      await page.route('**/api/plans', async (route) => {
        if (route.request().method() === 'POST' && !rejectedOnce) {
          rejectedOnce = true
          await route.fulfill({
            status: 422,
            contentType: 'application/json',
            body: JSON.stringify({
              detail: [
                {
                  loc: ['source_plan_id'],
                  msg: `source plan ${originalId} not found`,
                  type: 'value_error',
                },
              ],
            }),
          })
          return
        }
        await route.continue()
      })

      await page.getByTestId('segment-length-0').fill('650')
      await page.getByTestId('submit-plan').click()

      // error shown, all edits preserved, no new plan created
      await expect(page.getByTestId('source-error')).toBeVisible()
      await expect(page).toHaveURL(`/?from=${originalId}`)
      await expect(page.getByTestId('segment-length-0')).toHaveValue('650')
      await expect(page.getByTestId('segment-length-1')).toHaveValue('590')
      await expect(page.getByTestId('roll-length')).toHaveValue('1000')

      // re-pick the source; the retry succeeds with the edits intact
      await page.getByTestId('source-plan-input').fill(String(originalId))
      await page.getByTestId('source-plan-confirm').click()
      await expect(page.getByTestId('source-error')).toHaveCount(0)
      await page.getByTestId('submit-plan').click()
      await expect(page).toHaveURL(/\/plans\/\d+$/)
      const adjustedId = Number(page.url().split('/').pop())
      expect(adjustedId).not.toBe(originalId)
      await expect(page.getByText(/A（650 mm）/)).toBeVisible()
    })
  })
})
