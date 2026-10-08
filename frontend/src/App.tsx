import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { api } from "./api/client";
import { getPasscode, PASSCODE_EVENT } from "./lib/passcode";
import { ToastProvider } from "./lib/toast";
import Flashcards from "./screens/Flashcards";
import Making from "./screens/Making";
import Results from "./screens/Results";
import Reviewer from "./screens/Reviewer";
import Reviewers from "./screens/Reviewers";
import PasscodeSheet from "./sheets/PasscodeSheet";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 2000 } },
});

function PasscodeGate() {
  const [ask, setAsk] = useState<{ wrong: boolean } | null>(null);
  useEffect(() => {
    const onNeed = (e: Event) => setAsk({ wrong: !!(e as CustomEvent).detail?.wrong });
    window.addEventListener(PASSCODE_EVENT, onNeed);
    // Ask up front when the backend wants a passcode and we don't have one yet.
    api.get<{ passcode_required: boolean }>("/health").then((h) => {
      if (h.passcode_required && !getPasscode()) setAsk({ wrong: false });
    }).catch(() => {});
    return () => window.removeEventListener(PASSCODE_EVENT, onNeed);
  }, []);
  return ask ? <PasscodeSheet wrong={ask.wrong} onDone={() => setAsk(null)} /> : null;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Reviewers />} />
            <Route path="/reviewers/:id" element={<Reviewer />} />
            <Route path="/exams/:id/making" element={<Making />} />
            <Route path="/attempts/:id" element={<Flashcards />} />
            <Route path="/attempts/:id/summary" element={<Results />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          <PasscodeGate />
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}
