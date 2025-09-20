import React, { useState } from "react";
import { API_BASE_URL } from "../lib/api";

export default function ResumeUploader() {
  const [file, setFile] = useState(null);
  const [parsed, setParsed] = useState(null);
  const [loading, setLoading] = useState(false);
  const [rewrite, setRewrite] = useState(null);
  const [clJobTitle, setClJobTitle] = useState("");
  const [clCompany, setClCompany] = useState("");
  const [clJD, setClJD] = useState("");
  const [coverLetter, setCoverLetter] = useState(null);
  const [error, setError] = useState("");

  const handleUpload = async () => {
    if (!file) { setError("Choose a file first"); return; }
    setError(""); setLoading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`${API_BASE_URL}/resume/parse`, {
        method: "POST",
        body: fd
      });
      if (!res.ok) throw new Error("Parse failed");
      const data = await res.json();
      setParsed(data.parsed);
    } catch {
      setError("Upload/Parse failed");
    } finally {
      setLoading(false);
    }
  };

  const handleRewrite = async () => {
    if (!parsed) { setError("Parse a resume first"); return; }
    setError(""); setLoading(true); setRewrite(null);
    try {
      const res = await fetch(`${API_BASE_URL}/resume/rewrite`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          parsed,
          job_title: clJobTitle || undefined,
          company: clCompany || undefined,
          job_description: clJD || undefined
        })
      });
      if (!res.ok) throw new Error("Rewrite failed");
      const data = await res.json();
      setRewrite(data);
    } catch {
      setError("Rewrite failed");
    } finally {
      setLoading(false);
    }
  };

  const handleCover = async () => {
    if (!parsed || !clJobTitle) { setError("Enter job title and parse a resume first"); return; }
    setError(""); setLoading(true); setCoverLetter(null);
    try {
      const res = await fetch(`${API_BASE_URL}/resume/cover-letter`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          parsed,
          job_title: clJobTitle,
          company: clCompany || undefined,
          job_description: clJD || undefined,
          max_words: 220
        })
      });
      if (!res.ok) throw new Error("Cover letter failed");
      const data = await res.json();
      setCoverLetter(data.cover_letter);
    } catch {
      setError("Cover letter failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-5">
      <h1 className="text-2xl font-bold">ResumePro — Upload, Rewrite & Cover Letter</h1>

      <div className="p-4 border rounded">
        <p className="text-sm text-gray-600">Upload a .txt resume to parse. Then rewrite or generate a cover letter.</p>
        <input type="file" onChange={(e) => setFile(e.target.files?.[0] || null)} className="block my-3" />
        <button onClick={handleUpload} className="px-4 py-2 bg-blue-600 text-white rounded disabled:opacity-60" disabled={loading}>
          {loading ? "Working..." : "Upload & Parse"}
        </button>
        {error && <p className="text-red-600 mt-2">{error}</p>}
      </div>

      {parsed && (
        <div className="p-4 border rounded space-y-3">
          <h2 className="font-semibold">Parsed JSON</h2>
          <pre className="bg-gray-100 p-3 overflow-x-auto text-sm">{JSON.stringify(parsed, null, 2)}</pre>

          <div className="grid md:grid-cols-2 gap-4">
            <div className="p-3 border rounded">
              <h3 className="font-semibold mb-2">Rewrite Resume</h3>
              <input placeholder="Target Job Title (optional)" value={clJobTitle} onChange={(e)=>setClJobTitle(e.target.value)} className="border p-2 w-full mb-2" />
              <input placeholder="Company (optional)" value={clCompany} onChange={(e)=>setClCompany(e.target.value)} className="border p-2 w-full mb-2" />
              <textarea placeholder="Paste Job Description (optional)" value={clJD} onChange={(e)=>setClJD(e.target.value)} className="border p-2 w-full h-24 mb-2" />
              <button onClick={handleRewrite} className="px-3 py-2 bg-emerald-600 text-white rounded disabled:opacity-60" disabled={loading}>
                {loading ? "Rewriting..." : "Rewrite Resume"}
              </button>
            </div>

            <div className="p-3 border rounded">
              <h3 className="font-semibold mb-2">Generate Cover Letter</h3>
              <input placeholder="Job Title (required)" value={clJobTitle} onChange={(e)=>setClJobTitle(e.target.value)} className="border p-2 w-full mb-2" />
              <input placeholder="Company (optional)" value={clCompany} onChange={(e)=>setClCompany(e.target.value)} className="border p-2 w-full mb-2" />
              <textarea placeholder="Paste Job Description (optional)" value={clJD} onChange={(e)=>setClJD(e.target.value)} className="border p-2 w-full h-24 mb-2" />
              <button onClick={handleCover} className="px-3 py-2 bg-indigo-600 text-white rounded disabled:opacity-60" disabled={loading}>
                {loading ? "Generating..." : "Generate Cover Letter"}
              </button>
            </div>
          </div>

          {rewrite && (
            <div className="p-3 border rounded">
              <h3 className="font-semibold mb-2">Rewritten Resume</h3>
              <pre className="bg-gray-100 p-3 overflow-x-auto text-sm">{JSON.stringify(rewrite.rewritten, null, 2)}</pre>
              <h4 className="font-semibold mt-3">Printable Resume Text</h4>
              <pre className="bg-gray-100 p-3 overflow-x-auto text-sm whitespace-pre-wrap">{rewrite.resume_text}</pre>
              <p className="text-xs text-gray-500 mt-2">used_openai: {String(rewrite.used_openai)}</p>
            </div>
          )}

          {coverLetter && (
            <div className="p-3 border rounded">
              <h3 className="font-semibold mb-2">Cover Letter</h3>
              <pre className="bg-gray-100 p-3 overflow-x-auto text-sm whitespace-pre-wrap">{coverLetter}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
