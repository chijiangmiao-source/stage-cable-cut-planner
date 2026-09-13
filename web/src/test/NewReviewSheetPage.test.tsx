import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import NewReviewSheetPage from '../pages/NewReviewSheetPage'
import type { PlanOut, ReviewSheetOut } from '../types'

function plan(): PlanOut {
  // roll 1 = [A] leftover 400; roll 2 = [B, C] leftover 0
  return {
    id: 42,
    roll_length: 1000,
    kerf_width: 10,
    rolls_used: 2,
    total_kerf_count: 1,
    total_leftover: 400,
    completed_segment_count: 3,
    created_at: '2026-09-12T08:00:00Z',
    source_plan_id: null,
    rolls: [
      {
        position: 1,
        segments: [
          { id: 'A', length: 600, allowance: 0, kit_id: null, completed_at: '2026-09-12T09:00:00Z' },
        ],
        kerf_count: 0,
        used_length: 600,
        leftover: 400,
        completed_count: 1,
      },
      {
        position: 2,
        segments: [
          { id: 'B', length: 590, allowance: 0, kit_id: null, completed_at: '2026-09-12T09:01:00Z' },
          { id: 'C', length: 400, allowance: 0, kit_id: null, completed_at: '2026-09-12T09:02:00Z' },
        ],
        kerf_count: 1,
        used_length: 1000,
        leftover: 0,
        completed_count: 2,
      },
    ],
  }
}

function sheet(overrides: Partial<ReviewSheetOut> = {}): ReviewSheetOut {
  return {
    id: 7,
    plan_id: 42,
    tolerance_mm: 20,
    batch_ok: true,
    created_at: '2026-09-12T10:00:00Z',
    measurements: [
      { roll_position: 1, theoretical_leftover: 400, measured_leftover: 380, deviation: 20, ok: true },
      { roll_position: 2, theoretical_leftover: 0, measured_leftover: 20, deviation: 20, ok: true },
    ],
    ...overrides,
  }
}

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/plans/42/review']}>
      <Routes>
        <Route path="/plans/:id/review" element={<NewReviewSheetPage />} />
        <Route path="/review-sheets/:id" element={<p>复核单详情</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

/** Default load: plan found, no existing sheet (404 on the lookup). */
function mockLoad(fetchMock: ReturnType<typeof vi.fn>) {
  fetchMock
    .mockResolvedValueOnce(jsonResponse(plan()))
    .mockResolvedValueOnce(jsonResponse({ detail: 'review sheet not found' }, { status: 404 }))
}

describe('NewReviewSheetPage', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lists every roll in canonical order with its theoretical leftover', async () => {
    const fetchMock = vi.mocked(fetch)
    mockLoad(fetchMock)
    renderPage()

    await waitFor(() =>
      expect(screen.getByTestId('measured-roll-1')).toBeInTheDocument(),
    )
    expect(screen.getByText('理论余料 400 mm')).toBeInTheDocument()
    expect(screen.getByText('理论余料 0 mm')).toBeInTheDocument()
    expect(screen.getByTestId('measured-roll-2')).toBeInTheDocument()
    expect(screen.getByTestId('tolerance')).toHaveValue(20)
  })

  it('submits one measurement per roll and lands on the read-only detail', async () => {
    const fetchMock = vi.mocked(fetch)
    mockLoad(fetchMock)
    fetchMock.mockResolvedValueOnce(jsonResponse(sheet(), { status: 201 }))

    renderPage()
    const user = userEvent.setup()
    await waitFor(() => screen.getByTestId('measured-roll-1'))
    await user.clear(screen.getByTestId('tolerance'))
    await user.type(screen.getByTestId('tolerance'), '20')
    await user.type(screen.getByTestId('measured-roll-1'), '380')
    await user.type(screen.getByTestId('measured-roll-2'), '20')
    await user.click(screen.getByTestId('submit-review'))

    await waitFor(() =>
      expect(screen.getByText('复核单详情')).toBeInTheDocument(),
    )
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/review-sheets',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          plan_id: 42,
          tolerance_mm: 20,
          measurements: [
            { roll_position: 1, measured_leftover: 380 },
            { roll_position: 2, measured_leftover: 20 },
          ],
        }),
      }),
    )
  })

  it('maps 422 errors back to the fields and preserves every input', async () => {
    const fetchMock = vi.mocked(fetch)
    mockLoad(fetchMock)
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          detail: [
            { loc: ['tolerance_mm'], msg: 'tolerance too large', type: 'value_error' },
            {
              loc: ['measurements', 1, 'measured_leftover'],
              msg: 'measured value out of range',
              type: 'value_error',
            },
          ],
        },
        { status: 422 },
      ),
    )

    renderPage()
    const user = userEvent.setup()
    await waitFor(() => screen.getByTestId('measured-roll-1'))
    await user.clear(screen.getByTestId('tolerance'))
    await user.type(screen.getByTestId('tolerance'), '9999')
    await user.type(screen.getByTestId('measured-roll-1'), '380')
    await user.type(screen.getByTestId('measured-roll-2'), '20')
    await user.click(screen.getByTestId('submit-review'))

    await waitFor(() =>
      expect(screen.getByText('tolerance too large')).toBeInTheDocument(),
    )
    expect(screen.getByText('measured value out of range')).toBeInTheDocument()
    // the whole sheet input is preserved
    expect(screen.getByTestId('tolerance')).toHaveValue(9999)
    expect(screen.getByTestId('measured-roll-1')).toHaveValue(380)
    expect(screen.getByTestId('measured-roll-2')).toHaveValue(20)
  })

  it('shows a conflict on 409, keeps the inputs and links the existing sheet', async () => {
    const fetchMock = vi.mocked(fetch)
    mockLoad(fetchMock)
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ detail: '该方案已建立用料复核单，不能重复建单' }, { status: 409 }),
      )
      // conflict recovery: the existing sheet lookup now finds it
      .mockResolvedValueOnce(jsonResponse(sheet()))

    renderPage()
    const user = userEvent.setup()
    await waitFor(() => screen.getByTestId('measured-roll-1'))
    await user.type(screen.getByTestId('measured-roll-1'), '380')
    await user.type(screen.getByTestId('measured-roll-2'), '20')
    await user.click(screen.getByTestId('submit-review'))

    await waitFor(() =>
      expect(screen.getByTestId('review-conflict')).toBeInTheDocument(),
    )
    await waitFor(() =>
      expect(screen.getByTestId('review-existing-notice')).toBeInTheDocument(),
    )
    expect(
      screen.getByRole('link', { name: '查看复核单 #7' }),
    ).toHaveAttribute('href', '/review-sheets/7')
    // inputs survive the conflict, and resubmission is blocked
    expect(screen.getByTestId('measured-roll-1')).toHaveValue(380)
    expect(screen.getByTestId('measured-roll-2')).toHaveValue(20)
    expect(screen.getByTestId('submit-review')).toBeDisabled()
  })

  it('links the existing sheet and blocks submission when the plan already has one', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock
      .mockResolvedValueOnce(jsonResponse(plan()))
      .mockResolvedValueOnce(jsonResponse(sheet()))

    renderPage()
    await waitFor(() =>
      expect(screen.getByTestId('review-existing-notice')).toBeInTheDocument(),
    )
    expect(
      screen.getByRole('link', { name: '查看复核单 #7' }),
    ).toHaveAttribute('href', '/review-sheets/7')
    expect(screen.getByTestId('submit-review')).toBeDisabled()
  })

  it('validates locally and never calls the API on bad input', async () => {
    const fetchMock = vi.mocked(fetch)
    mockLoad(fetchMock)

    renderPage()
    const user = userEvent.setup()
    await waitFor(() => screen.getByTestId('measured-roll-1'))
    await user.clear(screen.getByTestId('tolerance'))
    await user.type(screen.getByTestId('tolerance'), '2.5')
    await user.type(screen.getByTestId('measured-roll-1'), '-1')
    await user.click(screen.getByTestId('submit-review'))

    await waitFor(() =>
      expect(screen.getByText(/允许偏差须为 0 至 10000 的整数毫米/)).toBeInTheDocument(),
    )
    // both the negative roll 1 value and the empty roll 2 input are flagged
    expect(
      screen.getAllByText(/实测余料须为 0 至 100000 的整数毫米/).length,
    ).toBeGreaterThanOrEqual(1)
    // only the two load requests happened
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
