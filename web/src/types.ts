export interface SegmentOut {
  id: string
  length: number
  allowance: number
  /** Kit (套组) marker: segments sharing one kit stay on one roll.
   *  null for independent segments and for every historical plan. */
  kit_id: string | null
  /** ISO timestamp once this segment has actually been cut; null otherwise. */
  completed_at: string | null
}

export interface RollOut {
  position: number
  segments: SegmentOut[]
  kerf_count: number
  used_length: number
  leftover: number
  completed_count: number
}

export interface PlanOut {
  id: number
  roll_length: number
  kerf_width: number
  rolls_used: number
  total_kerf_count: number
  total_leftover: number
  completed_segment_count: number
  created_at: string
  source_plan_id: number | null
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
  source_plan_id: number | null
}

export interface SegmentInput {
  id: string
  length: number
  allowance?: number
  /** Blank/omitted means an independent segment (legacy behavior). */
  kit_id?: string
}

export interface PlanCreateInput {
  roll_length: number
  kerf_width: number
  segments: SegmentInput[]
  source_plan_id?: number | null
}

export interface FieldError {
  loc: Array<string | number>
  msg: string
  type?: string
}

/** One roll's measured leftover, keyed by its canonical roll position. */
export interface ReviewMeasurementInput {
  roll_position: number
  measured_leftover: number
}

export interface ReviewSheetCreateInput {
  plan_id: number
  /** Uniform allowed deviation (mm) applied to every roll of the batch. */
  tolerance_mm: number
  measurements: ReviewMeasurementInput[]
}

export interface ReviewMeasurementOut {
  roll_position: number
  theoretical_leftover: number
  measured_leftover: number
  deviation: number
  /** Per-roll verdict: deviation within the uniform tolerance. */
  ok: boolean
}

export interface ReviewSheetOut {
  id: number
  plan_id: number
  tolerance_mm: number
  /** Whole-batch verdict: every roll within tolerance. */
  batch_ok: boolean
  created_at: string
  measurements: ReviewMeasurementOut[]
}
