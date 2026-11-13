import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { InviteGate, checkSession, type SessionState } from "./components/InviteGate";
import { Shell } from "./components/Shell";
import "./styles.css";

function Root() {
  const [session, setSession] = useState<SessionState>({ state: "checking", invite: false });
  useEffect(() => { void checkSession().then(setSession); }, []);
  if (session.state === "checking") return <div className="invite-gate" aria-busy="true" />;
  if (session.state === "need") return <InviteGate onDone={() => setSession({ state: "ok", invite: true })} />;
  return <Shell canLogout={session.invite} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
