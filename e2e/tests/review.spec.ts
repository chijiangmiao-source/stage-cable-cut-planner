import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

async function createAbcPlan(page: Page) {
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
  return Number(page.url().split('/').pop())
}

async function cutWholeBatch(page: Page) {
  // canonical solution: roll 1 = [A], roll 2 = [B, C]
  await page.getByTestId('complete-roll-1').click()
  await page.getByTestId('complete-roll-2').click()
  await page.getByTestId('complete-roll-2').click()
  await expect(page.getByTestId('overall-progress')).toHaveText('3 / 3 段（全部完成）')
}

test.describe('material review sheets (用料复核单)', () => {
  test('files a sheet after cutting, shows verdicts, survives refresh, and blocks duplicates', async ({
    page,
  }) => {
    const planId = await createAbcPlan(page)
    await cutWholeBatch(page)

    // enter the review form from the saved plan; canonical roll order and
    // theoretical leftovers come from the plan
    await page.getByTestId('create-review-sheet').click()
    await expect(page).toHaveURL(`/plans/${planId}/review`)
    await expect(page.getByText('理论余料 400 mm')).toBeVisible()
    await expect(page.getByText('理论余料 0 mm')).toBeVisible()

    // boundary deviations (exactly the tolerance) still pass
    await page.getByTestId('tolerance').fill('20')
    await page.getByTestId('measured-roll-1').fill('380')
    await page.getByTestId('measured-roll-2').fill('20')
    await page.getByTestId('submit-review').click()

    // read-only detail: theoretical/measured/deviation plus every verdict
    await expect(page).toHaveURL(/\/review-sheets\/\d+$/)
    await expect(page.getByTestId('batch-verdict')).toHaveText('整批结论：用料正常')
    const row1 = page.getByTestId('review-row-1')
    await expect(row1).toContainText('第 1 卷')
    await expect(row1).toContainText('400')
    await expect(row1).toContainText('380')
    await expect(row1).toContainText('20')
    await expect(page.getByTestId('roll-verdict-1')).toHaveText('合格')
    await expect(page.getByTestId('roll-verdict-2')).toHaveText('合格')
    await expect(page.getByTestId('back-to-plan')).toHaveAttribute(
      'href',
      `/plans/${planId}`,
    )

    // a full reload shows the identical persisted sheet
    await page.reload()
    await expect(page.getByTestId('batch-verdict')).toHaveText('整批结论：用料正常')
    await expect(page.getByTestId('review-row-1')).toContainText('380')
    await expect(page.getByTestId('roll-verdict-2')).toHaveText('合格')

    // filing a second sheet for the same plan is blocked with a link to the
    // existing one; the plan itself stays reachable and unchanged
    await page.goto(`/plans/${planId}`)
    await expect(page.getByTestId('overall-progress')).toHaveText('3 / 3 段（全部完成）')
    await page.getByTestId('create-review-sheet').click()
    await expect(page.getByTestId('review-existing-notice')).toBeVisible()
    await expect(page.getByTestId('submit-review')).toBeDisabled()
    await page.getByRole('link', { name: /查看复核单 #\d+/ }).click()
    await expect(page).toHaveURL(/\/review-sheets\/\d+$/)
    await expect(page.getByTestId('batch-verdict')).toHaveText('整批结论：用料正常')
  })

  test('an over-tolerance roll marks the whole batch abnormal', async ({
    page,
  }) => {
    await createAbcPlan(page)
    await cutWholeBatch(page)

    await page.getByTestId('create-review-sheet').click()
    await page.getByTestId('tolerance').fill('20')
    await page.getByTestId('measured-roll-1').fill('390')
    await page.getByTestId('measured-roll-2').fill('100')
    await page.getByTestId('submit-review').click()

    await expect(page).toHaveURL(/\/review-sheets\/\d+$/)
    await expect(page.getByTestId('batch-verdict')).toHaveText('整批结论：用料异常')
    await expect(page.getByTestId('roll-verdict-1')).toHaveText('合格')
    await expect(page.getByTestId('roll-verdict-2')).toHaveText('异常')
    await expect(page.getByTestId('review-row-2')).toContainText('100')

    // the abnormal verdict is persisted, not recomputed on the client
    await page.reload()
    await expect(page.getByTestId('batch-verdict')).toHaveText('整批结论：用料异常')
    await expect(page.getByTestId('roll-verdict-2')).toHaveText('异常')
  })

  test('422 errors are located on the sheet inputs and the whole input is preserved', async ({
    page,
  }) => {
    await createAbcPlan(page)
    await cutWholeBatch(page)

    await page.getByTestId('create-review-sheet').click()

    // simulate the server rejecting the sheet once (e.g. rules tightened
    // after the page was loaded): located 422 errors on both inputs
    let rejectedOnce = false
    await page.route('**/api/review-sheets', async (route) => {
      if (route.request().method() === 'POST' && !rejectedOnce) {
        rejectedOnce = true
        await route.fulfill({
          status: 422,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: [
              { loc: ['tolerance_mm'], msg: 'tolerance not accepted', type: 'value_error' },
              {
                loc: ['measurements', 1, 'measured_leftover'],
                msg: 'measured value rejected',
                type: 'value_error',
              },
            ],
          }),
        })
        return
      }
      await route.continue()
    })

    await page.getByTestId('tolerance').fill('20')
    await page.getByTestId('measured-roll-1').fill('380')
    await page.getByTestId('measured-roll-2').fill('20')
    await page.getByTestId('submit-review').click()

    // errors are mapped back onto the matching inputs...
    await expect(page.getByText('tolerance not accepted')).toBeVisible()
    await expect(page.getByText('measured value rejected')).toBeVisible()
    // ...and the whole sheet input is preserved
    await expect(page.getByTestId('tolerance')).toHaveValue('20')
    await expect(page.getByTestId('measured-roll-1')).toHaveValue('380')
    await expect(page.getByTestId('measured-roll-2')).toHaveValue('20')

    // correcting nothing but resubmitting now goes through
    await page.getByTestId('submit-review').click()
    await expect(page).toHaveURL(/\/review-sheets\/\d+$/)
    await expect(page.getByTestId('batch-verdict')).toHaveText('整批结论：用料正常')
  })
})
