import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  ApiError,
  createReviewSheet,
  getPlan,
  getPlanReviewSheet,
} from '../api'
import { groupErrors } from '../errors'
import type { PlanOut, ReviewSheetOut } from '../types'

const MAX_TOLERANCE = 10000
const MAX_MEASURED = 100000

function FieldErrors({ messages }: { messages?: string[] }) {
  if (!messages || messages.length === 0) return null
  return (
    <span className="field-error" role="alert">
      {messages.join('；')}
    </span>
  )
}

/** Build the material review sheet for a saved plan: the canonical roll
 *  order and theoretical leftovers come from the server, the foreman only
 *  types one integer measurement per roll plus the uniform tolerance. Any
 *  rejection (422/409) keeps every input in place. */
export default function NewReviewSheetPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [plan, setPlan] = useState<PlanOut | null>(null)
  const [existing, setExisting] = useState<ReviewSheetOut | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [tolerance, setTolerance] = useState('20')
  // Measured leftovers as typed, aligned with plan.rolls (canonical order).
  const [measured, setMeasured] = useState<string[]>([])
  const [errors, setErrors] = useState<Map<string, string[]>>(new Map())
  const [topError, setTopError] = useState<string | null>(null)
  const [conflict, setConflict] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!id) return
    let cancelled = false
    Promise.all([getPlan(id), getPlanReviewSheet(id)])
      .then(([loadedPlan, sheet]) => {
        if (cancelled) return
        setPlan(loadedPlan)
        setExisting(sheet)
        setMeasured(loadedPlan.rolls.map(() => ''))
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setLoadError(err instanceof Error ? err.message : '加载失败')
      })
    return () => {
      cancelled = true
    }
  }, [id])

  const fieldError = (key: string) => errors.get(key)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!plan || existing) return
    setTopError(null)
    setConflict(null)
    setErrors(new Map())

    // Light client-side check; the API remains the authority and its 422
    // errors are mapped back onto the same field keys below.
    const local = new Map<string, string[]>()
    const push = (key: string, msg: string) =>
      local.set(key, [...(local.get(key) ?? []), msg])
    const parseIntField = (
      raw: string,
      key: string,
      max: number,
      label: string,
    ): number => {
      const value = Number(raw)
      if (!raw.trim() || !Number.isInteger(value) || value < 0 || value > max) {
        push(key, `${label}须为 0 至 ${max} 的整数毫米`)
        return 0
      }
      return value
    }
    const tolerance_mm = parseIntField(
      tolerance,
      'tolerance_mm',
      MAX_TOLERANCE,
      '允许偏差',
    )
    const measurements = plan.rolls.map((roll, i) => ({
      roll_position: roll.position,
      measured_leftover: parseIntField(
        measured[i] ?? '',
        `measurements.${i}.measured_leftover`,
        MAX_MEASURED,
        '实测余料',
      ),
    }))
    if (local.size > 0) {
      setErrors(local)
      return
    }

    setSubmitting(true)
    try {
      const sheet = await createReviewSheet({
        plan_id: plan.id,
        tolerance_mm,
        measurements,
      })
      navigate(`/review-sheets/${sheet.id}`)
    } catch (err) {
      // 校验或冲突失败时整单输入原样保留，领班可直接修正后重新提交。
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setConflict(err.message)
          // Another foreman may have filed the sheet already; offer the
          // direct link to it.
          try {
            setExisting(await getPlanReviewSheet(plan.id))
          } catch {
            // keep the conflict notice even if the refetch fails
          }
        } else if (err.fieldErrors.length > 0) {
          setErrors(groupErrors(err.fieldErrors))
        } else {
          setTopError(err.message)
        }
      } else {
        setTopError('网络异常，请稍后重试')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section>
      <h2>建立用料复核单{plan ? `（方案 #${plan.id}）` : ''}</h2>
      {loadError && <p className="error-banner">{loadError}</p>}
      {!plan && !loadError && <p>加载中…</p>}
      {existing && (
        <p
          className="conflict-banner"
          role="alert"
          data-testid="review-existing-notice"
        >
          该方案已建立用料复核单，不能重复建单。
          <Link to={`/review-sheets/${existing.id}`}>
            查看复核单 #{existing.id}
          </Link>
        </p>
      )}
      {plan && (
        <form className="plan-form" onSubmit={onSubmit} noValidate>
          {topError && (
            <p className="error-banner" role="alert">
              {topError}
            </p>
          )}
          {conflict && (
            <p
              className="conflict-banner"
              role="alert"
              data-testid="review-conflict"
            >
              {conflict}
            </p>
          )}
          <div className="form-grid">
            <label>
              统一允许偏差（mm）
              <input
                data-testid="tolerance"
                type="number"
                min={0}
                max={MAX_TOLERANCE}
                step={1}
                required
                value={tolerance}
                onChange={(e) => setTolerance(e.target.value)}
              />
              <FieldErrors messages={fieldError('tolerance_mm')} />
            </label>
          </div>

          <fieldset>
            <legend>逐卷实测余料（按规范卷序）</legend>
            <p className="kit-hint">
              理论余料来自方案 #{plan.id} 的求解结果；每卷只录入一次整数毫米实测值，
              系统按 |实测 − 理论| 计算偏差，偏差 ≤ 允许偏差判定该卷合格，否则整批异常。
            </p>
            <FieldErrors messages={fieldError('measurements')} />
            {plan.rolls.map((roll, i) => (
              <div className="segment-row" key={roll.position}>
                <span className="segment-index">第 {roll.position} 卷</span>
                <span className="theoretical-leftover">
                  理论余料 {roll.leftover} mm
                </span>
                <label>
                  实测余料（mm）
                  <input
                    data-testid={`measured-roll-${roll.position}`}
                    type="number"
                    min={0}
                    max={MAX_MEASURED}
                    step={1}
                    required
                    value={measured[i] ?? ''}
                    onChange={(e) =>
                      setMeasured((prev) =>
                        prev.map((v, j) => (j === i ? e.target.value : v)),
                      )
                    }
                  />
                  <FieldErrors
                    messages={fieldError(`measurements.${i}.measured_leftover`)}
                  />
                  <FieldErrors
                    messages={fieldError(`measurements.${i}.roll_position`)}
                  />
                </label>
              </div>
            ))}
          </fieldset>

          <button
            type="submit"
            data-testid="submit-review"
            disabled={submitting || existing !== null}
          >
            {submitting ? '提交中…' : '提交复核单'}
          </button>
        </form>
      )}
    </section>
  )
}
