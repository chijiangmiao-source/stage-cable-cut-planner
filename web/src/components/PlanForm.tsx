import { useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, createPlan } from '../api'
import { groupErrors } from '../errors'
import {
  MAX_SEGMENTS,
  addRow,
  makeRow,
  removeRow,
  updateRow,
} from '../segmentRows'
import type { SegmentRow } from '../segmentRows'

function FieldErrors({ messages }: { messages?: string[] }) {
  if (!messages || messages.length === 0) return null
  return (
    <span className="field-error" role="alert">
      {messages.join('；')}
    </span>
  )
}

export default function PlanForm() {
  const navigate = useNavigate()
  const [rollLength, setRollLength] = useState('1000')
  const [kerfWidth, setKerfWidth] = useState('10')
  const [rows, setRows] = useState<SegmentRow[]>(() => [
    makeRow('S1', '600'),
    makeRow('S2', '590'),
    makeRow('S3', '400'),
  ])
  const [errors, setErrors] = useState<Map<string, string[]>>(new Map())
  const [topError, setTopError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const fieldError = (key: string) => errors.get(key)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setTopError(null)
    setErrors(new Map())

    // Light client-side check; the API remains the authority and its 422
    // errors are mapped back onto the same field keys below.
    const local = new Map<string, string[]>()
    const push = (key: string, msg: string) =>
      local.set(key, [...(local.get(key) ?? []), msg])
    const parseLen = (raw: string, key: string): number => {
      const value = Number(raw)
      if (!raw.trim() || !Number.isInteger(value) || value < 1 || value > 100000) {
        push(key, '长度须为 1 至 100000 的整数毫米')
        return 0
      }
      return value
    }
    const roll_length = parseLen(rollLength, 'roll_length')
    const kerf_width = parseLen(kerfWidth, 'kerf_width')
    const segments = rows.map((row, i) => {
      const id = row.id.trim()
      if (!id) push(`segments.${i}.id`, '编号不能为空')
      return { id, length: parseLen(row.length, `segments.${i}.length`) }
    })
    if (local.size > 0) {
      setErrors(local)
      return
    }

    setSubmitting(true)
    try {
      const plan = await createPlan({ roll_length, kerf_width, segments })
      navigate(`/plans/${plan.id}`)
    } catch (err) {
      // 校验失败时表单状态原样保留，领班可直接修正后重新提交。
      if (err instanceof ApiError) {
        if (err.fieldErrors.length > 0) setErrors(groupErrors(err.fieldErrors))
        else setTopError(err.message)
      } else {
        setTopError('网络异常，请稍后重试')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="plan-form" onSubmit={onSubmit} noValidate>
      {topError && (
        <p className="error-banner" role="alert">
          {topError}
        </p>
      )}

      <div className="form-grid">
        <label>
          卷长（mm）
          <input
            data-testid="roll-length"
            type="number"
            min={1}
            max={100000}
            step={1}
            required
            value={rollLength}
            onChange={(e) => setRollLength(e.target.value)}
          />
          <FieldErrors messages={fieldError('roll_length')} />
        </label>
        <label>
          锯口宽度（mm）
          <input
            data-testid="kerf-width"
            type="number"
            min={1}
            max={100000}
            step={1}
            required
            value={kerfWidth}
            onChange={(e) => setKerfWidth(e.target.value)}
          />
          <FieldErrors messages={fieldError('kerf_width')} />
        </label>
      </div>

      <fieldset>
        <legend>需求线段（{rows.length} / {MAX_SEGMENTS} 条）</legend>
        {rows.map((row, i) => (
          <div className="segment-row" key={row.key}>
            <span className="segment-index">#{i + 1}</span>
            <label>
              编号
              <input
                data-testid={`segment-id-${i}`}
                type="text"
                maxLength={32}
                required
                value={row.id}
                onChange={(e) => setRows(updateRow(rows, row.key, { id: e.target.value }))}
              />
              <FieldErrors messages={fieldError(`segments.${i}.id`)} />
            </label>
            <label>
              长度（mm）
              <input
                data-testid={`segment-length-${i}`}
                type="number"
                min={1}
                max={100000}
                step={1}
                required
                value={row.length}
                onChange={(e) =>
                  setRows(updateRow(rows, row.key, { length: e.target.value }))
                }
              />
              <FieldErrors messages={fieldError(`segments.${i}.length`)} />
            </label>
            <button
              type="button"
              data-testid={`remove-segment-${i}`}
              disabled={rows.length <= 1}
              onClick={() => setRows(removeRow(rows, row.key))}
            >
              删除
            </button>
          </div>
        ))}
        <button
          type="button"
          data-testid="add-segment"
          disabled={rows.length >= MAX_SEGMENTS}
          onClick={() => setRows(addRow(rows))}
        >
          添加线段
        </button>
      </fieldset>

      <button type="submit" data-testid="submit-plan" disabled={submitting}>
        {submitting ? '计算中…' : '生成裁切方案'}
      </button>
    </form>
  )
}
