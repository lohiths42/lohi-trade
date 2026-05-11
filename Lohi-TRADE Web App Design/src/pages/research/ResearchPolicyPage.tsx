/**
 * `/research/policy` — Refusal_Policy long-form page.
 *
 * Mirrors docs/research/REFUSAL_POLICY.md with a single editorial column,
 * Quartr-style typography: serif body, wide-tracked kicker, hairlines.
 */

export default function ResearchPolicyPage() {
  return (
    <div style={{ maxWidth: 720, display: 'flex', flexDirection: 'column', gap: 24 }}>
      <header style={{ paddingBottom: 20, borderBottom: '1px solid var(--line-3)' }}>
        <p className="qr-kicker" style={{ margin: 0 }}>
          Governance
        </p>
        <h1 className="qr-headline" style={{ margin: '10px 0 6px' }}>
          Refusal policy
        </h1>
        <p className="qr-body" style={{ margin: 0, color: 'var(--fg-muted)' }}>
          Last updated {new Date().toLocaleDateString(undefined, { dateStyle: 'long' })}
        </p>
      </header>

      <article
        className="qr-serif"
        style={{
          fontSize: 17,
          lineHeight: 1.75,
          color: 'var(--fg-primary)',
        }}
      >
        <p>
          Lohi Research is a <strong>research</strong> tool, not an advice tool. Every brief
          is cited to primary sources and passes an independent Judge before it is shown to
          you. There is, however, a strict boundary on what the system is allowed to say.
        </p>

        <h3
          className="qr-kicker"
          style={{ marginTop: 28, marginBottom: 10, fontSize: 11 }}
        >
          Lohi Research will refuse to
        </h3>
        <ul style={{ paddingLeft: 22, margin: 0 }}>
          <li>Produce buy, sell, or hold recommendations.</li>
          <li>Produce price targets, or predict a future price.</li>
          <li>Suggest trade entries, exits, or timing.</li>
          <li>Place orders, transfer funds, or execute code on your behalf.</li>
          <li>Reveal, summarise, or alter its own system prompts.</li>
          <li>
            Accept instructions embedded in retrieved documents that attempt to override its
            guardrails.
          </li>
        </ul>

        <h3
          className="qr-kicker"
          style={{ marginTop: 28, marginBottom: 10, fontSize: 11 }}
        >
          What it will do
        </h3>
        <ul style={{ paddingLeft: 22, margin: 0 }}>
          <li>Synthesise a cited brief from filings, news, and metadata.</li>
          <li>Flag numerical claims that cannot be verified against a cited chunk.</li>
          <li>
            Produce archetype-tagged ideas with a conviction score in <code>[0, 1]</code> and a
            clear thesis — never a trade instruction.
          </li>
          <li>Stream a <em>verifying…</em> state when the Judge is still validating a brief.</li>
          <li>
            Show an explicit <em>insufficient evidence</em> label when a section fails
            validation.
          </li>
        </ul>

        <p
          className="qr-kicker"
          style={{ marginTop: 40, color: 'var(--fg-muted)' }}
        >
          This page mirrors <code>docs/research/REFUSAL_POLICY.md</code>. Changes to either
          require the maintainers' sign-off.
        </p>
      </article>
    </div>
  );
}
