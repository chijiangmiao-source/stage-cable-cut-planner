import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getReviewSheet } from '../api'
import type { ReviewSheetOut } from '../types'

/** Read-only review sheet: theoretical vs measured leftover per roll, the
 *  absolute deviation, each roll's verdict and the whole-batch verdict.
 *  Everything comes from the persisted sheet, so a refresh shows the exact
 *  same numbers. */
export default function ReviewSheetDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [sheet, setSheet] = useState<ReviewSheetOut | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    getReviewSheet(id)
      .then(setSheet)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : '加载失败'),
      )
  }, [id])

  return (
    <section>
      {error && <p className="error-banner">{error}</p>}
      {!sheet && !error && <p>加载中…</p>}
      {sheet && (
        <>
          <h2>用料复核单 #{sheet.id}</h2>
          <p
            className={
              sheet.batch_ok ? 'verdict-banner verdict-ok' : 'verdict-banner verdict-bad'
            }
            data-testid="batch-verdict"
          >
            整批结论：{sheet.batch_ok ? '用料正常' : '用料异常'}
          </p>
          <dl className="summary">
            <div>
              <dt>关联方案</dt>
              <dd>
                <Link to={`/plans/${sheet.plan_id}`} data-testid="back-to-plan">
                  方案 #{sheet.plan_id}
                </Link>
              </dd>
            </div>
            <div>
              <dt>统一允许偏差</dt>
              <dd>{sheet.tolerance_mm} mm</dd>
            </div>
            <div>
              <dt>创建时间</dt>
              <dd>{new Date(sheet.created_at).toLocaleString()}</dd>
            </div>
          </dl>

          <h3>逐卷复核</h3>
          <table className="plan-table review-table">
            <thead>
              <tr>
                <th>卷序</th>
                <th>理论余料 (mm)</th>
                <th>实测余料 (mm)</th>
                <th>绝对偏差 (mm)</th>
                <th>结论</th>
              </tr>
            </thead>
            <tbody>
              {sheet.measurements.map((m) => (
                <tr key={m.roll_position} data-testid={`review-row-${m.roll_position}`}>
                  <td>第 {m.roll_position} 卷</td>
                  <td>{m.theoretical_leftover}</td>
                  <td>{m.measured_leftover}</td>
                  <td>{m.deviation}</td>
                  <td>
                    <span
                      className={m.ok ? 'verdict-tag verdict-ok' : 'verdict-tag verdict-bad'}
                      data-testid={`roll-verdict-${m.roll_position}`}
                    >
                      {m.ok ? '合格' : '异常'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  )
}
