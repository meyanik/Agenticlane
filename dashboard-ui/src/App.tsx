/** Main app with React Router. */

import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { HomePage } from './pages/HomePage';
import { RunDetailPage } from './pages/RunDetailPage';
import { LiveRunPage } from './pages/LiveRunPage';
import { NewRunPage } from './pages/NewRunPage';
import { StageDetailPage } from './pages/StageDetailPage';
import { AgentLogsPage } from './pages/AgentLogsPage';

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-container">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/new" element={<NewRunPage />} />
          <Route path="/logs" element={<AgentLogsPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="/runs/:runId/live" element={<LiveRunPage />} />
          <Route path="/runs/:runId/stages/:stage" element={<StageDetailPage />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
