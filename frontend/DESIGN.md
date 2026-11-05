# TrustFeed dashboard design

## Character

A forensic blacklight desk. Evidence fluoresces under the lamp, and anything not known stays dark and dashed. The honesty rules in `AGENT_COORDINATION.md` are the visual language, so a reader can tell what kind of information they're looking at before reading it.

## The memorable thing

The spread replay. Accounts light up as they join, against a time bar where sharp pink spikes show flagged groups and a flat trickle shows other posts. It opens the home page and fills the Spread tab, and it always runs on real API data. Keep everything around it quiet.

## Tokens

The custom properties at the top of `src/styles.css` are the source of truth. Don't add near-duplicate colours.

| Token | Value | Use |
| --- | --- | --- |
| `--ink`, `--ink-2`, `--ink-3` | `#17123a`, `#1f1949`, `#2b2460` | Page, raised surface, hover and empty tracks |
| `--paper`, `--soft` | `#f3f0ff`, `#c0b9e6` | Main and secondary text |
| `--uv` | `#eef25a` | Primary action, selected tab, marked words, synthetic tape, focus ring |
| `--flag` | `#ff4f8b` | Flagged group, concerns |
| `--cyan` | `#6fe7ff` | Observed evidence, links, mentioned accounts |
| `--low` to `--inconclusive` | see the file | The five risk levels |

**Type:** Big Shoulders Display for headings and the verdict word, Atkinson Hyperlegible Next for reading, and Atkinson Hyperlegible Mono only for hashes, case ids and account handles. All three are bundled through `@fontsource-variable`, so the demo needs no internet.

## Visual rules

| Meaning | How it looks | Where |
| --- | --- | --- |
| Observed | Solid cyan square and bullets | Evidence, pages found, posts |
| Estimate | Yellow hatching | Every score meter |
| Not known | Dashed outline with nothing inside | `No score`, checks not run, undated events, platforms not connected |
| Synthetic or replay | Yellow and indigo hazard tape | Top of the case, spread stage, source search, action packet, home graph |
| Risk | Verdict word, huge | Inconclusive is outlined, never filled, because it isn't a finding |
| Account role | Colour and shape | Earliest found has a ring and mentioned accounts are diamonds, so role doesn't rest on colour alone |

A real `0.00` draws an empty solid track and a null draws a dashed one. They must never look the same.

## Layout

- A sticky top bar, then full-width bands. Reports aren't split into identical cards.
- A case reads top to bottom: tape, verdict, one strip with a column per separate question, then tabs.
- Spread is full width and sized so the graph, controls and time bar fit on one screen when presenting.
- Below 1000 px, columns stack. Below 680 px, the top bar wraps and nothing scrolls sideways except wide tables.

## Motion

Only the home replay starts by itself, and it plays once. Everything else answers an action: a flash when an account joins, a scan line while an image is checked. Reduced motion jumps the replay to its end and removes the flashes and scan line.

## Do not drift

- No gradients as decoration, shadows under cards, or new fonts.
- Don't make a disabled integration look live.
- Don't call the earliest account the source, or a review signal proof.
- Don't load images from `image_url` in results. They're untrusted, and fetching them would tell the host who is looking.
