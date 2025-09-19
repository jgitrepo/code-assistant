import React, { useState } from "react";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import Skeleton from "./components/Skeleton.jsx";

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

const MODELS = [
  { id: "qwen3", label: "Qwen3 (Hugging Face)" },
  { id: "deepseek-3.1", label: "DeepSeek 3.1 (Hugging Face)" }
];

export default function App(){
  const [code, setCode] = useState(`def add(a, b):
    return a+b

def sum_two(x, y):
    return x+y
`);
  const [model, setModel] = useState(MODELS[0].id);
  const [loading, setLoading] = useState(false);
  const [explain, setExplain] = useState("");
  const [analysis, setAnalysis] = useState(null);
  const [aiResponse, setAiResponse] = useState("");
  const [error, setError] = useState("");

  async function callApi(endpoint, body){
    setError("");
    setLoading(true);
    try{
      const res = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      if(!res.ok){
        const txt = await res.text();
        throw new Error(`${res.status} ${res.statusText}: ${txt}`);
      }
      return await res.json();
    } catch(err){ setError(err.message); throw err; }
    finally { setLoading(false); }
  }

  const onExplain = async ()=>{
    const data = await callApi("/api/explain", { code, model });
    setExplain(data.explanation || "");
  };

  const onAnalyze = async ()=>{
    const data = await callApi("/api/analyze", { code });
    setAnalysis(data);
  };

  const onInfer = async ()=>{
    const data = await callApi("/api/infer", {
      model,
      prompt: `Review this code. Identify smells, suggest DRY refactors, and show best practices.\n\n${code}`
    });
    setAiResponse(data.text || "");
  };

  return (
    <ErrorBoundary>
      <div className="max-w-6xl mx-auto p-6">
        <header className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">AI-Driven Code Assistant</h1>
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-600">Model:</label>
            <select
              className="px-3 py-2 border rounded-lg bg-white"
              value={model}
              onChange={(e)=>setModel(e.target.value)}
              aria-label="Model selection"
            >
              {MODELS.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </div>
        </header>

        <div className="grid md:grid-cols-2 gap-6">
          <section className="space-y-2">
            <label className="text-sm font-medium text-gray-700">Your Code</label>
            <textarea
              className="w-full h-72 p-3 border rounded-xl font-mono text-sm"
              value={code}
              onChange={(e)=>setCode(e.target.value)}
            />
            <div className="flex flex-wrap gap-2">
              <button onClick={onExplain} className="px-4 py-2 rounded-xl bg-blue-600 text-white hover:brightness-110 disabled:opacity-60" disabled={loading}>
                Explain
              </button>
              <button onClick={onAnalyze} className="px-4 py-2 rounded-xl bg-emerald-600 text-white hover:brightness-110 disabled:opacity-60" disabled={loading}>
                Analyze (Lint + DRY)
              </button>
              <button onClick={onInfer} className="px-4 py-2 rounded-xl bg-indigo-600 text-white hover:brightness-110 disabled:opacity-60" disabled={loading}>
                AI Refactor Ideas
              </button>
            </div>
            {error && (
              <div className="mt-2 p-3 text-sm bg-red-50 text-red-700 border border-red-200 rounded-xl">
                {error}
              </div>
            )}
          </section>

          <section className="space-y-4">
            <div className="p-4 bg-white rounded-2xl border">
              <h2 className="font-semibold">Explainability</h2>
              {loading ? <Skeleton className="h-24 mt-2"/> :
                <pre className="whitespace-pre-wrap text-sm mt-2">{explain || "—"}</pre>}
            </div>

            <div className="p-4 bg-white rounded-2xl border">
              <h2 className="font-semibold">Static Analysis (Best Practices & DRY)</h2>
              {loading ? <Skeleton className="h-28 mt-2"/> :
                analysis ? (
                  <div className="text-sm mt-2 space-y-2">
                    <div>
                      <h3 className="font-medium">Findings</h3>
                      <ul className="list-disc pl-5">
                        {analysis.findings.map((f,i)=> <li key={i}>{f}</li>)}
                      </ul>
                    </div>
                    {analysis.refactors?.length ? (
                      <div>
                        <h3 className="font-medium">Refactor Suggestions</h3>
                        <ul className="list-disc pl-5">
                          {analysis.refactors.map((r,i)=> <li key={i}><code>{r.symbol}</code>: {r.suggestion}</li>)}
                        </ul>
                      </div>
                    ) : null}
                    {analysis.formatted && (
                      <details className="mt-2">
                        <summary className="cursor-pointer">Auto-formatted (preview)</summary>
                        <pre className="mt-2 p-2 bg-gray-50 rounded border overflow-auto">{analysis.formatted}</pre>
                      </details>
                    )}
                  </div>
                ) : "—"}
            </div>

            <div className="p-4 bg-white rounded-2xl border">
              <h2 className="font-semibold">AI Refactor Ideas (HF Inference)</h2>
              {loading ? <Skeleton className="h-24 mt-2"/> :
                <pre className="whitespace-pre-wrap text-sm mt-2">{aiResponse || "—"}</pre>}
            </div>
          </section>
        </div>

        <footer className="text-xs text-gray-500 mt-8">
          FastAPI backend at <code>{API_BASE}</code>
        </footer>
      </div>
    </ErrorBoundary>
  );
}
