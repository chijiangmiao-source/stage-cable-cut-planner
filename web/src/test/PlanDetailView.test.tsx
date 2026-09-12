import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import PlanDetailView from '../components/PlanDetailView'
import type { PlanOut } from '../types'

const plan: PlanOut = {
  id: 7,
  roll_length: 1000,
  kerf_width: 10,
  rolls_used: 2,
  total_kerf_count: 1,
  total_leftover: 400,
  created_at: '2026-09-12T08:00:00Z',
  source_plan_id: null,
  rolls: [
    {
      position: 1,
      segments: [{ id: 'A', length: 600 }],
      kerf_count: 0,
      used_length: 600,
      leftover: 400,
    },
    {
      position: 2,
      segments: [
        { id: 'B', length: 590 },
        { id: 'C', length: 400 },
      ],
      kerf_count: 1,
      used_length: 1000,
      leftover: 0,
    },
  ],
}

function renderView(viewPlan: PlanOut = plan) {
  return render(
    <MemoryRouter>
      <PlanDetailView plan={viewPlan} />
    </MemoryRouter>,
  )
}

describe('PlanDetailView', () => {
  it('shows totals and per-roll cutting order, kerfs and leftovers', () => {
    const { container } = renderView()
    const text = container.textContent ?? ''

    expect(screen.getByText('第 1 卷')).toBeInTheDocument()
    expect(screen.getByText('第 2 卷')).toBeInTheDocument()

    // cutting order with lengths so the foreman can recompute
    expect(text).toContain('A（600 mm）')
    expect(text).toContain('B（590 mm） → C（400 mm）')

    // per-roll arithmetic: 590+400 + 1×10 kerf = 1000 ≤ 1000, leftover 0
    expect(text).toContain('990（线长合计）+ 1 × 10（锯口）= 1000 mm ≤ 1000 mm；余料 0 mm；锯口 1 次')
    expect(text).toContain('600（线长合计）+ 0 × 10（锯口）= 600 mm ≤ 1000 mm；余料 400 mm；锯口 0 次')

    // totals
    expect(text).toContain('总余料')
    expect(text).toContain('400 mm')
  })

  it('offers an "adjust from this plan" entry point', () => {
    renderView()
    const adjust = screen.getByTestId('adjust-from-plan')
    expect(adjust.textContent).toContain('基于此方案调整')
    expect(adjust.getAttribute('href')).toBe('/?from=7')
  })

  it('hides the source line for plans without a source', () => {
    renderView({ ...plan, source_plan_id: null })
    expect(screen.queryByTestId('source-line')).not.toBeInTheDocument()
    expect(screen.queryByText('源自方案')).not.toBeInTheDocument()
  })

  it('links to the source plan when provenance exists', () => {
    renderView({ ...plan, id: 9, source_plan_id: 7 })
    const sourceLine = screen.getByTestId('source-line')
    const link = sourceLine.querySelector('a')
    expect(link).not.toBeNull()
    expect(link?.getAttribute('href')).toBe('/plans/7')
    expect(link?.textContent).toBe('#7')
    // the adjust entry of the new plan points at the new plan itself
    expect(screen.getByTestId('adjust-from-plan').getAttribute('href')).toBe('/?from=9')
  })
})
