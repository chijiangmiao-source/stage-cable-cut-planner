import { Link, Route, Routes } from 'react-router-dom'
import NewPlanPage from './pages/NewPlanPage'
import PlanListPage from './pages/PlanListPage'
import PlanDetailPage from './pages/PlanDetailPage'
import NewReviewSheetPage from './pages/NewReviewSheetPage'
import ReviewSheetDetailPage from './pages/ReviewSheetDetailPage'

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <h1>信号线裁切规划</h1>
        <nav>
          <Link to="/">新建方案</Link>
          <Link to="/plans">历史方案</Link>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<NewPlanPage />} />
          <Route path="/plans" element={<PlanListPage />} />
          <Route path="/plans/:id" element={<PlanDetailPage />} />
          <Route path="/plans/:id/review" element={<NewReviewSheetPage />} />
          <Route path="/review-sheets/:id" element={<ReviewSheetDetailPage />} />
        </Routes>
      </main>
    </div>
  )
}
