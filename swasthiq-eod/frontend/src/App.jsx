import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import Reconciliation from "./pages/Reconciliation.jsx";
import Analytics from "./pages/Analytics.jsx";
import Narrative from "./pages/Narrative.jsx";

// Layout (sidebar + date picker) wraps every screen, so it persists across all three.
export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/reconciliation" replace />} />
        <Route path="/reconciliation" element={<Reconciliation />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/narrative" element={<Narrative />} />
        <Route path="*" element={<Navigate to="/reconciliation" replace />} />
      </Route>
    </Routes>
  );
}
