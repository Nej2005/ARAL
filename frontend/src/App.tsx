import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { ToastProvider } from "./lib/toast";
import Flashcards from "./screens/Flashcards";
import Making from "./screens/Making";
import Results from "./screens/Results";
import Reviewer from "./screens/Reviewer";
import Reviewers from "./screens/Reviewers";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 2000 } },
});

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
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}
