/**
 * API base URL used by the frontend.
 * Reads from Vite env (VITE_API_BASE). Falls back to your Render URL.
 */
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE || "https://resumepro-backend-437b.onrender.com";
