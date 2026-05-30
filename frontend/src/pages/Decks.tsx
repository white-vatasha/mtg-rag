import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import {
  createDeck,
  deleteDeck,
  listDecks,
  updateDeck,
  type Deck,
} from "../api/client";
import { useAuth } from "../context/AuthContext";

const EMPTY_FORM = {
  name: "",
  commander: "",
  description: "",
  cards: "",
};

export default function Decks() {
  const { user, loading: authLoading } = useAuth();
  const [decks, setDecks] = useState<Deck[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  const loadDecks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listDecks();
      setDecks(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load decks");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user) loadDecks();
  }, [user, loadDecks]);

  if (!authLoading && !user) {
    return <Navigate to="/login" replace />;
  }

  function startCreate() {
    setEditingId(null);
    setForm(EMPTY_FORM);
  }

  function startEdit(deck: Deck) {
    setEditingId(deck.id);
    setForm({
      name: deck.name,
      commander: deck.commander ?? "",
      description: deck.description ?? "",
      cards: deck.cards,
    });
  }

  function cancelForm() {
    setEditingId(null);
    setForm(EMPTY_FORM);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const payload = {
      name: form.name.trim(),
      commander: form.commander.trim() || undefined,
      description: form.description.trim() || undefined,
      cards: form.cards,
    };
    try {
      if (editingId) {
        await updateDeck(editingId, payload);
      } else {
        await createDeck(payload);
      }
      cancelForm();
      await loadDecks();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save deck");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this deck?")) return;
    try {
      await deleteDeck(id);
      if (editingId === id) cancelForm();
      await loadDecks();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete");
    }
  }

  return (
    <div className="page decks-page">
      <header className="page-header">
        <div>
          <h1>My Decks</h1>
          <p className="muted">Save Commander lists you are brewing or playing.</p>
        </div>
        <button type="button" className="btn-primary" onClick={startCreate}>
          + New deck
        </button>
      </header>

      {error && <div className="card error-card">{error}</div>}

      <div className="decks-layout">
        <section className="deck-list card">
          {loading ? (
            <p className="muted">Loading decks…</p>
          ) : decks.length === 0 ? (
            <p className="muted">No decks yet. Create your first list.</p>
          ) : (
            <ul>
              {decks.map((deck) => (
                <li key={deck.id} className={editingId === deck.id ? "active" : ""}>
                  <button type="button" className="deck-row" onClick={() => startEdit(deck)}>
                    <strong>{deck.name}</strong>
                    {deck.commander && <span>{deck.commander}</span>}
                  </button>
                  <button
                    type="button"
                    className="btn-danger-sm"
                    onClick={() => handleDelete(deck.id)}
                    aria-label={`Delete ${deck.name}`}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card deck-editor">
          <h2>{editingId ? "Edit deck" : "New deck"}</h2>
          <form onSubmit={handleSubmit}>
            <label htmlFor="deck-name">Deck name</label>
            <input
              id="deck-name"
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
            <label htmlFor="commander">Commander</label>
            <input
              id="commander"
              placeholder="e.g. Korvold, Fae-Cursed King"
              value={form.commander}
              onChange={(e) => setForm({ ...form, commander: e.target.value })}
            />
            <label htmlFor="description">Notes</label>
            <textarea
              id="description"
              rows={2}
              placeholder="Strategy, bracket, upgrades…"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
            <label htmlFor="cards">Card list</label>
            <textarea
              id="cards"
              rows={12}
              placeholder={"1 Sol Ring\n1 Command Tower\n…"}
              value={form.cards}
              onChange={(e) => setForm({ ...form, cards: e.target.value })}
            />
            <div className="form-actions">
              <button type="submit" className="btn-primary" disabled={saving}>
                {saving ? "Saving…" : editingId ? "Update deck" : "Save deck"}
              </button>
              {(editingId || form.name) && (
                <button type="button" className="btn-ghost" onClick={cancelForm}>
                  Cancel
                </button>
              )}
            </div>
          </form>
        </section>
      </div>

      {!user && !authLoading && (
        <p>
          <Link to="/login">Log in</Link> to save decks.
        </p>
      )}
    </div>
  );
}
