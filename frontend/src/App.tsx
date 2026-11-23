import { useState } from "react";
import { StackTrendsView } from "./components/analytics/StackTrendsView";
import { type ActiveTab, AppShell } from "./components/layout/AppShell";
import { JobRadarView } from "./components/radar/JobRadarView";
import { PipelineTrackerView } from "./components/tracker/PipelineTrackerView";
import { useAlertStream } from "./hooks/useAlertStream";

export function App() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("radar");
  const { alerts, connected, dismissAlert } = useAlertStream();

  return (
    <AppShell
      activeTab={activeTab}
      onSelectTab={setActiveTab}
      sseConnected={connected}
      alerts={alerts}
      onDismissAlert={dismissAlert}
    >
      {activeTab === "radar" && <JobRadarView />}
      {activeTab === "tracker" && <PipelineTrackerView />}
      {activeTab === "analytics" && <StackTrendsView />}
    </AppShell>
  );
}

export default App;