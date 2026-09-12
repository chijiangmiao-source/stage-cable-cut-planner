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
    parts.push(
      <div
        key={`seg-${seg.id}`}
        className="rollbar-segment"
        style={{ width: `${(seg.length / rollLength) * 100}%` }}
        title={`${seg.id}: ${seg.length} mm`}
      >
        {seg.id}
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
