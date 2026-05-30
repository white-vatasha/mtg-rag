import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { createDeck, type ExtractedDecklist } from "../api/client";
import { useAuth } from "../context/AuthContext";

interface Props {
  decklist: ExtractedDecklist;
  question: string;
  answer: string;
}

export default function SaveDeckFromAnswer({ decklist, question, answer }: Props) {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const defaultName =
    decklist.name ||
    (decklist.commander ? `${decklist.commander} — Oracle save` : "Deck from Oracle");

  const [name, setName] = useState(defaultName);
  const [commander, setCommander] = useState(decklist.commander ?? "");
  const [cards, setCards] = useState(decklist.cards);
  const [description, setDescription] = useState(
    decklist.description ||
      `Saved from Commander Oracle.\n\nQuestion: ${question}\n\n${answer.slice(0, 1500)}`
  );

  if (!user) {
    return (
      <div className="save-deck-banner">
        <p>
          This answer includes a decklist ({decklist.card_count} cards).
          <Link to="/login"> Log in</Link> to save it to My Decks.
        </p>
      </div>
    );
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await createDeck({
        name: name.trim(),
        commander: commander.trim() || undefined,
        description: description.trim() || undefined,
        cards,
      });
      setSaved(true);
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save deck");
    } finally {
      setSaving(false);
    }
  }

  if (saved) {
    return (
      <div className="save-deck-banner ok">
        <p>
          Deck saved to <Link to="/decks">My Decks</Link>.
        </p>
      </div>
    );
  }

  return (
    <div className="save-deck-panel">
      <div className="save-deck-banner">
        <p>
          Detected a Commander decklist ({decklist.card_count} cards)
          {decklist.commander ? ` — ${decklist.commander}` : ""}.
        </p>
        <button type="button" className="btn-primary" onClick={() => setOpen((v) => !v)}>
          {open ? "Cancel" : "Save to My Decks"}
        </button>
      </div>

      {open && (
        <form className="save-deck-form" onSubmit={handleSave}>
          <label htmlFor="save-deck-name">Deck name</label>
          <input
            id="save-deck-name"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <label htmlFor="save-deck-commander">Commander</label>
          <input
            id="save-deck-commander"
            value={commander}
            onChange={(e) => setCommander(e.target.value)}
          />
          <label htmlFor="save-deck-cards">Card list</label>
          <textarea
            id="save-deck-cards"
            rows={10}
            value={cards}
            onChange={(e) => setCards(e.target.value)}
          />
          <label htmlFor="save-deck-notes">Notes</label>
          <textarea
            id="save-deck-notes"
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          {error && <p className="form-error">{error}</p>}
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? "Saving…" : "Save deck"}
          </button>
        </form>
      )}
    </div>
  );
}
