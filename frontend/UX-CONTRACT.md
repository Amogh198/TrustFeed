# TrustFeed frontend UX contract

The dashboard shows real API responses. It holds no sample data of its own, and the only canned content is the labelled replay data the API serves.

## Main flows

1. **New investigation:** submit text, a link, or an image or video. Results show every module, why each check reached its result, and what it can't show.
2. **Case report:** assessment, modules, explanation, heatmap on request (images uploaded in this session), source search, timeline, how it spread, and an action packet.
3. **Monitoring:** watch text, links or hashtags, and poll when you choose. Nothing runs in the background.
4. **Demos:** `demo-001`, the linked story `demo-story-001` and the replay scenarios work with no internet.

## State rules

| State | Required UI behaviour |
| --- | --- |
| Empty text or link | Explain what is missing and stay on the page. |
| Search opt-in | Unticked by default. Say what is sent: the image to source search services, and the text and links to Mastodon, Lemmy, Hacker News and Bluesky search. |
| Waiting | Disable submit, and allow up to 3 minutes with an honest progress message. |
| Rejected upload | Show a clear message for 411, 413, 415 and 422. |
| `unavailable`, `not_applicable` | Look different from a real result. A null score reads "No score", never 0. |
| Low or inconclusive media | Say that this does not show the media is authentic. |
| Source search | Always show `earliest_found.caveat`. Never call that page the source or the original. |
| Undated timeline events | Stay visible in their own group, with no invented date. |
| Network score | Read as a "Review signal". Never as proof of coordination. |
| Coverage | Show which platforms were searched, which were not connected, and why. Null means no trace ran. |
| Synthetic or replay data | Labelled wherever it appears. |
| Untrusted text | Page titles, handles and evidence are plain text, and only http and https links are clickable. |
| Benchmark | A null benchmark reads "Not measured". |

Run the API and then `npm run smoke:api` to check the client's main routes against real responses.
