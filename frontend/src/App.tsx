import { Navigate, Route, Routes } from 'react-router-dom';
import type { ReactNode } from 'react';
import Layout from '@/components/Layout';
import Login from '@/pages/Login';
import Dashboard from '@/pages/Dashboard';
import Live from '@/pages/Live';
import Recordings from '@/pages/Recordings';
import Events from '@/pages/Events';
import Cameras from '@/pages/Cameras';
import Settings from '@/pages/Settings';
import { useHasRole, useIsAuthenticated } from '@/stores/auth';
import type { Role } from '@/lib/api';

function RequireAuth({ children }: { children: ReactNode }) {
  const authed = useIsAuthenticated();
  if (!authed) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function RequireRole({ min, children }: { min: Role; children: ReactNode }) {
  const ok = useHasRole(min);
  if (!ok) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Dashboard />} />
        <Route path="/live" element={<Live />} />
        <Route path="/recordings" element={<Recordings />} />
        <Route path="/events" element={<Events />} />
        <Route path="/cameras" element={<Cameras />} />
        <Route
          path="/settings/*"
          element={
            <RequireRole min="admin">
              <Settings />
            </RequireRole>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
