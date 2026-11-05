# TrustFeed frontend design context

## Product character

TrustFeed is an evidence desk for reviewing risky claims. Its visual signature is a quiet field-notebook workspace: warm off-white surfaces, forest-green action states, restrained amber for caution, and monospace metadata. It should feel calm and inspectable, never like a verdict engine.

## Canonical runtime tokens

The CSS custom properties in `src/styles.css` are the implementation source of truth. Keep new UI mapped to these tokens rather than introducing near-duplicate literals.

| Intent | Runtime token | Use |
| --- | --- | --- |
| Primary text | `--ink` | headings and important labels |
| Secondary text | `--muted` | supporting copy and metadata |
| Rules | `--line` | panel and section separators |
| Surface | `--panel` | cards and tables |
| Primary action | `--green` / `--green-dark` | CTAs and selected navigation |
| Soft positive state | `--green-soft` | replay and local-context surfaces |
| Metadata | `--mono` | case IDs, timestamps, status labels |
| Headings | `--heading` | hierarchy and case titles |

## Evidence language

Every report must distinguish three kinds of information in both language and colour:

- Observed evidence: a specific record in the supplied data.
- Heuristic estimate: an analytical indicator, never a factual conclusion.
- Unknown or unavailable: a capability, source, or fact that was not present.

Risk is an invitation to review. Origin candidates, network roles, and model-like summaries are leads, not attribution, identity verification, or proof of intent.

## Layout and interaction

- Desktop uses a stable left workspace rail and a readable, bounded content column.
- Case reports progress from assessment to provenance, evidence, dissemination, and next action.
- Small screens collapse the rail into a menu and stack report panels without hiding caveats.
- All controls need visible keyboard focus; graph nodes support Enter and Space.
- Motion is brief and removed when the user requests reduced motion.

## Do not drift

Do not add a generic dashboard aesthetic, gradients as decoration, or a new font dependency. Do not make a disabled integration look live. Preserve the replay notice and use explicit unavailable states when data or services are absent.
