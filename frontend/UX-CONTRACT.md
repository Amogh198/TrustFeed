# TrustFeed dashboard UX contract

The dashboard shows real API responses. It holds no sample data of its own, and the only canned content is the labelled replay data the API serves. Product copy on the "What it misses" page comes from `AGENT_COORDINATION.md`, and must change when that file does.

## Routes

Every view has its own address, so a demo can be reloaded or bookmarked at any step.

| Address | View |
| --- | --- |
| `#/` | Check form, spread replay, demos, recent cases, platforms covered |
| `#/case/{id}/{tab}` | Case report. Tabs: `findings`, `media`, `text`, `source`, `spread`, `timeline`, `action` |
| `#/cases` | Saved cases, filtered by risk and searchable |
| `#/watch` | Monitoring: start, poll, stop |
| `#/walkthrough` | The demo script, with a button for each step |
| `#/limits` | Each official requirement, what it does and what it doesn't |

## State rules

| State | Required UI behaviour |
| --- | --- |
| Empty text or link | Explain what is missing and stay on the page. |
| Search opt-in | Unticked by default. Say what is sent: the image to source search services, and the text and links to Mastodon, Lemmy, Hacker News and Bluesky search. |
| Waiting | Replace the form with what's running and the time so far, with no invented percentage. Allow up to 3 minutes, and let the user stop waiting. |
| Rejected upload | Refuse wrong types and sizes before sending. Show a clear message for 411, 413, 415 and 422. |
| API not running | Show a banner with the command to start it, and reconnect by itself. |
| A view fails to render | Show a message and a reload button. The rest of the app keeps working. |
| `unavailable`, `not_applicable` | Look different from a real result. A null score reads "No score", never 0. |
| Trust score | Comes from `unified_risk.trust_score` on the server, which counts only measured signals: the media detector when it shows signals, scam signs and the link address check. Above 50 only for a clean link with positive evidence (brand's own domain, domain age, not on threat feeds). Otherwise never above 50, and at most 40 at moderate and 25 at high or critical. 50 reads "Inconclusive: not enough evidence", and the page says it's a neutral midpoint, not a measurement. Spread and source search aren't counted. With nothing measured it reads "No trust score" and never a number. Cases saved earlier use the older calculation in `format.ts`. |
| Reasoning | Each check's result and reasoning are visible on Findings without opening anything. |
| Model not running | Say the media check didn't run, and give the install command. |
| Low or inconclusive media | Say that this does not show the media is authentic. |
| Source search | Always show `earliest_found.caveat`. Never call that page the source or the original. |
| Undated timeline events | Stay visible in their own group, with no invented date. |
| Network score | Read as a "Review signal". Never as proof of coordination. |
| Coverage | Show which platforms were searched, which were not connected, and why. Null means no trace ran. |
| Synthetic or replay data | Hazard tape wherever it appears, and on exports and drafts. |
| Untrusted text | Page titles, handles and evidence are plain text, and only http and https links are clickable. Images from result URLs are never loaded. |
| Benchmark | A null benchmark reads "Not measured". |
| Action packet | Say it comes from fixed rules. The correction card is a draft a person must confirm. |
| Watch | Show a countdown for the 60-second poll limit, and nothing runs in the background. |
| Times | Evidence times are shown in UTC. |
| Keyboard | Every control works by keyboard. On the graph, arrow keys step through accounts, Enter or Space opens one, and plus and minus zoom. |

## Checks

```bash
npm run check
```

That runs the type check, lint, tests and build. With the API running, `npm run smoke:api` checks the client's main routes against real responses.
