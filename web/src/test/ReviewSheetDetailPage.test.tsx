import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import ReviewSheetDetailPage from '../pages/ReviewSheetDetailPage'
import type { ReviewSheetOut } from '../types'

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
    <MemoryRouter initialEntries={['/review-sheets/7']}>
      <Routes>
        <Route path="/review-sheets/:id" element={<ReviewSheetDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ReviewSheetDetailPage', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows theoretical, measured, deviation and per-roll/batch verdicts', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse(sheet()))

    renderPage()
    await waitFor(() =>
      expect(screen.getByTestId('batch-verdict')).toHaveTextContent('用料正常'),
    )
    expect(screen.getByTestId('back-to-plan')).toHaveAttribute('href', '/plans/42')
    expect(screen.getByText('统一允许偏差')).toBeInTheDocument()
    expect(screen.getByText('20 mm')).toBeInTheDocument()

    const row1 = screen.getByTestId('review-row-1')
    expect(row1).toHaveTextContent('第 1 卷')
    expect(row1).toHaveTextContent('400')
    expect(row1).toHaveTextContent('380')
    expect(row1).toHaveTextContent('20')
    expect(screen.getByTestId('roll-verdict-1')).toHaveTextContent('合格')
    expect(screen.getByTestId('roll-verdict-2')).toHaveTextContent('合格')
  })

  it('marks an over-tolerance roll and the whole batch as abnormal', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        sheet({
          batch_ok: false,
          measurements: [
            { roll_position: 1, theoretical_leftover: 400, measured_leftover: 390, deviation: 10, ok: true },
            { roll_position: 2, theoretical_leftover: 0, measured_leftover: 100, deviation: 100, ok: false },
          ],
        }),
      ),
    )

    renderPage()
    await waitFor(() =>
      expect(screen.getByTestId('batch-verdict')).toHaveTextContent('用料异常'),
    )
    expect(screen.getByTestId('roll-verdict-1')).toHaveTextContent('合格')
    expect(screen.getByTestId('roll-verdict-2')).toHaveTextContent('异常')
    expect(screen.getByTestId('review-row-2')).toHaveTextContent('100')
  })

  it('shows an error banner when the sheet cannot be loaded', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: 'review sheet not found' }, { status: 404 }),
    )

    renderPage()
    await waitFor(() =>
      expect(screen.getByText('review sheet not found')).toBeInTheDocument(),
    )
  })
})
