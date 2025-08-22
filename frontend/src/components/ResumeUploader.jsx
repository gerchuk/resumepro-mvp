import { useState } from "react";
import api from "../lib/api";

export default function ResumeUploader() {
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const onUpload = async () => {
    setError("");
    setResult(null);
    if (!file) {
      setError("Please choose a file first.");
      return;
    }
    try {
      const fd = new FormData();
      // IMPORTANT: backend expects the key to be exactly 'file'
      fd.append("file", file);

      const res = await api.post("/resume/parse", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResult(res.data);
    } catch (e) {
      console.error(e);
      setError(e?.response?.data?.detail || "Upload failed. Check backend logs.");
    }
  };

  return (
    <div style={{ maxWidth: 720, margin: "2rem auto", padding: 16, border: "1px solid #eee", borderRadius: 12 }}>
      <h1 style={{ marginTop: 0 }}>ResumePro — Upload & Parse</h1>
      <p style={{ marginTop: 0, color: "#555" }}>
        Choose a <code>.txt</code> (or a simple <code>.docx/.pdf</code> that extracts as text) resume to parse.
      </p>

      <input
        type="file"
        onChange={(e) => setFile(e.target.files?.[0] || null)}
        accept=".txt,.pdf,.doc,.docx"
      />
      <div style={{ marginTop: 12 }}>
        <button onClick={onUpload}>Upload & Parse</button>
      </div>

      {error && (
        <pre style={{ background: "#fee", padding: 12, whiteSpace: "pre-wrap", color: "#900", marginTop: 12 }}>
          {error}
        </pre>
      )}

      {result && (
        <pre style={{ background: "#f6f8fa", padding: 12, whiteSpace: "pre-wrap", marginTop: 12 }}>
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
    </div>
  );
}
