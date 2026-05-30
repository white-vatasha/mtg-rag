import { FormEvent, useEffect, useState } from "react";
import { askCommander, checkHealth, type QueryResult } from "../api/client";
import SaveDeckFromAnswer from "../components/SaveDeckFromAnswer";

const SAMPLE_QUESTIONS = [
  "What are strong cEDH commanders right now?",
  "Suggest a Voltron build around Light-Paws, Emperor's Voice.",
  "Which commanders pair well with artifact sacrifice?",
  "What cards show up most in competitive Korvold lists?",
];

export default function Home() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [ragReady, setRagReady] = useState<boolean | null>(null);
  const [indexStatus, setIndexStatus] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const poll = () => {
      checkHealth()
        .then((h) => {
          if (!active) return;
          setRagReady(h.rag_ready);
          if (!h.rag_ready && h.indexing_message) {
            setIndexStatus(`${h.indexing_phase}: ${h.indexing_message}`);
          } else {
            setIndexStatus(null);
          }
        })
        .catch(() => {
          if (active) setRagReady(false);
        });
    };
    poll();
    const id = setInterval(poll, 8000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (q.length < 3) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await askCommander(q);
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page home-page">
      <section className="hero">
        <p className="eyebrow">Commander / EDH intelligence</p>
        <h1>Ask about built Commander decks</h1>
        <p className="lead">
          Search card rules and real decklists from the meta. Get recommendations on
          commanders, synergies, and competitive builds.
        </p>
        {ragReady === false && (
          <div className="banner warn">
            {indexStatus ||
              "RAG engine is warming up or unavailable. Start Ollama and run indexing first."}
          </div>
        )}
        {ragReady === true && (
          <div className="banner ok">Knowledge base ready.</div>
        )}
      </section>

      <form className="query-form card" onSubmit={handleSubmit}>
        <label htmlFor="question">Your question</label>
        <textarea
          id="question"
          rows={4}
          placeholder="e.g. What are the top competitive Atraxa superfriends shells?"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={loading}
        />
        <div className="form-actions">
          <button type="submit" className="btn-primary" disabled={loading || question.trim().length < 3}>
            {loading ? "Consulting the oracle…" : "Ask Commander Oracle"}
          </button>
        </div>
        <div className="samples">
          <span>Try:</span>
          {SAMPLE_QUESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              className="chip"
              onClick={() => setQuestion(s)}
              disabled={loading}
            >
              {s}
            </button>
          ))}
        </div>
      </form>

      {error && <div className="card error-card">{error}</div>}

      {result && (
        <section className="card answer-card">
          <h2>Answer</h2>
          {result.color_identity && (
            <p className="color-identity-note">
              Building for color identity: <strong>{result.color_identity}</strong>
            </p>
          )}
          {result.has_decklist && result.decklist && (
            <SaveDeckFromAnswer
              decklist={result.decklist}
              question={question.trim()}
              answer={result.answer}
            />
          )}
          <div className="answer-body">{result.answer}</div>
          {result.sources.length > 0 && (
            <details className="sources">
              <summary>Sources ({result.sources.length})</summary>
              <ul>
                {result.sources.map((src, i) => (
                  <li key={i}>
                    <p>{src.snippet}</p>
                    {src.metadata?.name != null ? (
                      <span className="meta-tag">{String(src.metadata.name)}</span>
                    ) : null}
                    {Boolean(src.metadata?.is_decklist) && (
                      <span className="meta-tag deck">Decklist</span>
                    )}
                    {Boolean(src.metadata?.is_edhrec_meta) && (
                      <span className="meta-tag deck">EDHRec meta</span>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </section>
      )}
    </div>
  );
}
