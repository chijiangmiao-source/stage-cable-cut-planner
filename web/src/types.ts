export interface SegmentOut {
  id: string
  length: number
}

export interface RollOut {
  position: number
  segments: SegmentOut[]
  kerf_count: number
  used_length: number
  leftover: number
}

export interface PlanOut {
  id: number
  roll_length: number
  kerf_width: number
  rolls_used: number
  total_kerf_count: number
  total_leftover: number
  created_at: string
  rolls: RollOut[]
}

export interface PlanSummary {
  id: number
  roll_length: number
  kerf_width: number
  segment_count: number
  rolls_used: number
  total_kerf_count: number
  total_leftover: number
  created_at: string
}

export interface SegmentInput {
  id: string
  length: number
}

export interface PlanCreateInput {
  roll_length: number
  kerf_width: number
  segments: SegmentInput[]
}

export interface FieldError {
  loc: Array<string | number>
  msg: string
  type?: string
}
