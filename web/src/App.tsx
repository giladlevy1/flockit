import { Navigate, Route, Routes, useLocation } from "react-router";

import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
import { useMe, useSetupStatus } from "./lib/auth";
import { AiDeveloperPage } from "./pages/AiDeveloper";
import { AiDevelopersPage } from "./pages/AiDevelopers";
import { AuditPage } from "./pages/Audit";
import { ConnectPage } from "./pages/Connect";
import { LoginPage } from "./pages/Login";
import { PeoplePage } from "./pages/People";
import { SearchPage } from "./pages/Search";
import { SessionPage } from "./pages/SessionPage";
import { SetupPage } from "./pages/Setup";
import { TasksPage } from "./pages/Tasks";
import { WorkflowsPage } from "./pages/Workflows";
import { WorkPage } from "./pages/Work";

function FullPageSpinner() {
  return (
    <div className="flex min-h-dvh items-center justify-center text-muted">
      <Spinner className="size-5" />
    </div>
  );
}

export function App() {
  const setup = useSetupStatus();
  const me = useMe();
  const location = useLocation();

  if (setup.isLoading || me.isLoading) return <FullPageSpinner />;

  if (setup.data?.needs_setup) {
    return (
      <Routes>
        <Route path="/setup" element={<SetupPage />} />
        <Route path="*" element={<Navigate to="/setup" replace />} />
      </Routes>
    );
  }

  if (!me.data) {
    const next = location.pathname !== "/login" ? `?next=${encodeURIComponent(location.pathname + location.search)}` : "";
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to={`/login${next}`} replace />} />
      </Routes>
    );
  }

  return (
    <Layout me={me.data}>
      <Routes>
        <Route path="/" element={<WorkPage me={me.data} />} />
        <Route path="/sessions/:id" element={<SessionPage me={me.data} />} />
        <Route path="/tasks" element={<TasksPage me={me.data} />} />
        <Route path="/workflows" element={<WorkflowsPage me={me.data} />} />
        <Route path="/ai" element={<AiDevelopersPage me={me.data} />} />
        <Route path="/ai/:id" element={<AiDeveloperPage me={me.data} />} />
        <Route path="/search" element={<SearchPage me={me.data} />} />
        {me.data.user.role === "admin" && <Route path="/audit" element={<AuditPage />} />}
        <Route path="/people" element={<PeoplePage me={me.data} />} />
        <Route path="/connect" element={<ConnectPage me={me.data} />} />
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route path="/setup" element={<Navigate to="/connect" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
