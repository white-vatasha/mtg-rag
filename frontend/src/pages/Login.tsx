import { FormEvent, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function Login() {
  const { user, loading, login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!loading && user) return <Navigate to="/decks" replace />;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page auth-page">
      <div className="card auth-card">
        <h1>{mode === "login" ? "Log in" : "Create account"}</h1>
        <p className="muted">
          Save and manage your Commander decklists in one place.
        </p>
        <form onSubmit={handleSubmit}>
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && <p className="form-error">{error}</p>}
          <button type="submit" className="btn-primary full" disabled={submitting}>
            {submitting ? "Please wait…" : mode === "login" ? "Log in" : "Sign up"}
          </button>
        </form>
        <p className="switch-mode">
          {mode === "login" ? (
            <>
              New here?{" "}
              <button type="button" className="link-btn" onClick={() => setMode("register")}>
                Create an account
              </button>
            </>
          ) : (
            <>
              Already have an account?{" "}
              <button type="button" className="link-btn" onClick={() => setMode("login")}>
                Log in
              </button>
            </>
          )}
        </p>
        <Link to="/" className="back-link">
          ← Back to Ask
        </Link>
      </div>
    </div>
  );
}
