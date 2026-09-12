import type { PlanOut } from '../types'
import RollBar from './RollBar'

/** Read-only rendering of a persisted plan; every roll shows the full
 *  arithmetic so the foreman can recompute it by hand. */
export default function PlanDetailView({ plan }: { plan: PlanOut }) {
  return (
    <div className="plan-detail">
      <dl className="summary">
        <div>
          <dt>卷长</dt>
          <dd>{plan.roll_length} mm</dd>
        </div>
        <div>
          <dt>锯口宽度</dt>
          <dd>{plan.kerf_width} mm</dd>
        </div>
        <div>
          <dt>线卷数</dt>
          <dd>{plan.rolls_used}</dd>
        </div>
        <div>
          <dt>总锯口</dt>
          <dd>{plan.total_kerf_count} 次</dd>
        </div>
        <div>
          <dt>总余料</dt>
          <dd>{plan.total_leftover} mm</dd>
        </div>
        <div>
          <dt>创建时间</dt>
          <dd>{new Date(plan.created_at).toLocaleString()}</dd>
        </div>
      </dl>

      <h3>逐卷裁切方案</h3>
      {plan.rolls.map((roll) => {
        const lengthSum = roll.segments.reduce((acc, s) => acc + s.length, 0)
        return (
          <section key={roll.position} className="roll-card">
            <h4>第 {roll.position} 卷</h4>
            <RollBar
              roll={roll}
              rollLength={plan.roll_length}
              kerfWidth={plan.kerf_width}
            />
            <p className="cutting-order">
              裁切顺序：
              {roll.segments.map((s) => `${s.id}（${s.length} mm）`).join(' → ')}
            </p>
            <p className="roll-math">
              {lengthSum}（线长合计）+ {roll.kerf_count} × {plan.kerf_width}
              （锯口）= {roll.used_length} mm ≤ {plan.roll_length} mm；余料{' '}
              {roll.leftover} mm；锯口 {roll.kerf_count} 次
            </p>
          </section>
        )
      })}
    </div>
  )
}
