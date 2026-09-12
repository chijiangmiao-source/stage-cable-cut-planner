import { render, screen } from '@testing-library/react'
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

describe('PlanDetailView', () => {
  it('shows totals and per-roll cutting order, kerf counts and leftovers', () => {
    const { container } = render(<PlanDetailView plan={plan} />)
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
})
