import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getPlan } from '../api'
import PlanDetailView from '../components/PlanDetailView'
import type { PlanOut } from '../types'

export default function PlanDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [plan, setPlan] = useState<PlanOut | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    getPlan(id)
      .then(setPlan)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : '加载失败'),
      )
  }, [id])

  return (
    <section>
      {error && <p className="error-banner">{error}</p>}
      {!plan && !error && <p>加载中…</p>}
      {plan && (
        <>
          <h2>方案 #{plan.id}</h2>
          <PlanDetailView plan={plan} />
        </>
      )}
    </section>
  )
}
