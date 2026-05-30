import { Link, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function Layout() {
  const { user, logout, loading } = useAuth();

  return (
    <div className="app-shell">
      <header className="topbar">
        <Link to="/" className="brand">
          <span className="brand-mark">◇</span>
          Commander Oracle
        </Link>
        <nav className="nav-links">
          <Link to="/">Ask</Link>
          <Link to="/decks">My Decks</Link>
          {!loading && (
            user ? (
              <>
                <span className="user-pill">{user.email}</span>
                <button type="button" className="btn-ghost" onClick={logout}>
                  Log out
                </button>
              </>
            ) : (
              <Link to="/login" className="btn-primary nav-cta">
                Log in
              </Link>
            )
          )}
        </nav>
      </header>
      <main className="main-content">
        <Outlet />
      </main>
      <footer className="footer">
        Powered by your local Commander RAG — card rules &amp; competitive decklists.
      </footer>
    </div>
  );
}
