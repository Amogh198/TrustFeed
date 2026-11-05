# TrustFeed: Golden Path Demo Pitch

**Run time: 3 minutes.** This scenario and its accounts are fictional. Use connected live sources only when configured and authorized; otherwise label the dashboard view as replay/demo data.

## The Hook (0:00–0:30)

“A false emergency can spread across platforms faster than a human team can search, compare, and brief decision-makers. Most response workflows are manual: someone spots a post, someone else checks the evidence, and the response starts after the rumor has already traveled. In a public-safety moment, that delay can create real harm. The challenge is to see the coordinated pattern early and give people a responsible next step.”

## The Solution (0:30–1:00)

“TrustFeed is an AI-driven monitoring and response workspace. It brings posts from configured sources into one view, looks for signals that may indicate coordinated or manipulated content, traces how a claim spreads, and assembles evidence for a human to review. The goal is faster triage across text, links, account behavior, and media—not an automatic verdict.”

## Live Walkthrough Talk-Track (1:00–2:30)

### Action 1 — Live Threat Radar (1:00–1:20)

**Presenter:** “First, we look at the Live Threat Radar. Here we can scan activity from the platforms connected for this demo and see emerging claims together instead of searching each one manually. I’m opening our fictional water-alert scenario. The timestamps and source labels let us separate what the system observed from what it infers.”

**Show:** Radar view; point to platform/source labels, time window, and the claim cluster. If live connectors are unavailable, switch to the labeled synthetic replay and say so.

### Action 2 — Cropped, watermarked image (1:20–1:42)

**Presenter:** “Next, we upload this heavily cropped, watermarked image. The media-forensics path uses OpenCV preprocessing and perceptual-hash comparison to look for visually similar media even when an image has been resized or recompressed. The result is a similarity lead for review; cropping, overlays, or substantial edits can reduce the match, so we treat it as evidence to inspect rather than proof of origin.”

**Show:** Upload the prepared fictional image fixture, then point to the media match/similarity output and its confidence or limitation labels. Do not use a real emergency image.

### Action 3 — Dissemination graph (1:42–2:05)

**Presenter:** “The system maps the bot-ring spread. We can see one origin account, fifteen near-identical posts appearing within forty-five seconds, and then five large synthetic amplifier accounts repeating the same claim. That timing, repeated text, shared link, and media hash form a pattern worth investigating. The graph is a view of this fixture’s known structure, not a claim about real users.”

**Show:** Graph visualization; trace origin → coordinated burst → amplifiers. Call out the displayed time window and synthetic-data label.

### Action 4 — LLM Action Packet (2:05–2:30)

**Presenter:** “Finally, we generate the LLM Action Packet. It brings together the claim, observed posts, spread pattern, media match, and uncertainty into a platform-ready review draft, including a proposed notice for the relevant trust-and-safety team. A person checks the evidence and edits or rejects the draft before anything is sent. TrustFeed prepares a response; it does not automatically file takedowns.”

**Show:** Generate the packet; point to cited evidence, draft notice, and review controls. If the current build uses a template fallback, describe it as an assembled draft rather than claiming model-generated text.

## The Impact (2:30–3:00)

“TrustFeed brings multi-platform monitoring, dissemination tracing, and resilient media comparison into one response flow. It makes the timeline and evidence easier to inspect, while keeping synthetic fixtures, measured signals, and uncertainty visible. That gives a response team a faster, more reviewable starting point when coordinated false content is moving quickly—and keeps the final decision with people.”

## Demo setup notes

- Load `data/demo/judges_pitch_scenario.json` as the scenario reference. The fixture is standalone and does not add a backend loader or change the API contract.
- Prepare a fictional water-plant notice image with a visible watermark and crop it before the demo; do not present an image as real incident evidence.
- Confirm platform connectors, model access, and image-forensics services in the actual build before claiming live results. Use the current fallback honestly if any service is unavailable.
- Keep the inference/estimate label visible on the graph and packet. Avoid calling follower counts, bot labels, or hash similarity independently verified facts.
