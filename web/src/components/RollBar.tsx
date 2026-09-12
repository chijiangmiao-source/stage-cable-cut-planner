import type { ReactElement } from 'react'
import type { RollOut } from '../types'

interface Props {
  roll: RollOut
  rollLength: number
  kerfWidth: number
}

/** Proportional bar: segments, kerf gaps between them, leftover at the tail. */
export default function RollBar({ roll, rollLength, kerfWidth }: Props) {
  const parts: ReactElement[] = []
  roll.segments.forEach((seg, i) => {
    const isDone = seg.completed_at != null
    const isNext = !isDone && i === roll.completed_count
    const stateClass = isDone
      ? 'rollbar-segment is-done'
      : isNext
        ? 'rollbar-segment is-next'
        : 'rollbar-segment'
    parts.push(
      <div
        key={`seg-${seg.id}`}
        className={stateClass}
        style={{ width: `${(seg.length / rollLength) * 100}%` }}
        title={
          isDone
            ? `${seg.id}: ${seg.length} mm（已裁切 ${new Date(seg.completed_at as string).toLocaleString()}）`
            : isNext
              ? `${seg.id}: ${seg.length} mm（下一段待切）`
              : `${seg.id}: ${seg.length} mm`
        }
      >
        {isDone ? `✓ ${seg.id}` : seg.id}
      </div>,
    )
    if (i < roll.segments.length - 1) {
      parts.push(
        <div
          key={`kerf-${i}`}
          className="rollbar-kerf"
          style={{ width: `${(kerfWidth / rollLength) * 100}%` }}
          title={`锯口 ${kerfWidth} mm`}
        />,
      )
    }
  })
  if (roll.leftover > 0) {
    parts.push(
      <div
        key="leftover"
        className="rollbar-leftover"
        style={{ width: `${(roll.leftover / rollLength) * 100}%` }}
        title={`余料 ${roll.leftover} mm`}
      />,
    )
  }
  return <div className="rollbar">{parts}</div>
}
