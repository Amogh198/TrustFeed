const REQUIREMENTS: [string, 'partial' | 'built', string, string][] = [
  ['Multi-platform monitoring', 'partial', 'Reads public search on Mastodon, Lemmy, Hacker News and Bluesky when you ask.', "Reddit and YouTube need credentials. X and private channels aren't covered. It isn't a complete feed, and images in posts aren't analysed."],
  ['Multi-format content ingestion', 'partial', 'Takes text, links, images and videos.', "It doesn't take audio on its own, and it doesn't read text inside images."],
  ['AI-based synthetic media detection', 'partial', 'Runs one image model, and shows its score and its tested accuracy on every media case.', 'At its current settings it flags very few fakes, so a quiet result means little.'],
  ['Deepfake detection', 'partial', 'Runs the image model on images and video keyframes, plus a heatmap of what moved the score.', "There's no audio, lip-sync or motion analysis, and face swaps weren't tested."],
  ['Dissemination network tracing', 'built', 'Finds real posts by link, text or hashtag on four platforms, then groups accounts that repeatedly post the same items close together.', "Accuracy on real campaigns hasn't been measured. It's only been shown on synthetic data built to contain a campaign."],
  ['Countermeasures', 'built', 'Drafts an action packet and a correction card from the evidence in a case.', "Drafts come from fixed rules, not a generative model, and claims aren't checked against outside sources."],
];

export default function Limits() {
  return (
    <div className="page">
      <header className="page-head">
        <h1>What it covers and what it misses</h1>
        <p>Built for LAKSHYA 2026, problem DL-SJBIT-HK26-GOVP006. The brief is to monitor several platforms, take in many formats of social media content, use AI models to detect synthetic media and deepfakes, and trace how coordinated disinformation spreads.</p>
      </header>
      <div className="table-scroll">
        <table className="table table-limits">
          <thead><tr><th>Requirement</th><th>State</th><th>What it does</th><th>What it doesn't do</th></tr></thead>
          <tbody>
            {REQUIREMENTS.map(([name, state, does, doesnt]) => (
              <tr key={name}>
                <th scope="row">{name}</th>
                <td><span className={`state state-${state}`}>{state === 'built' ? 'Built' : 'Partial'}</span></td>
                <td>{does}</td>
                <td>{doesnt}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <section className="section">
        <header className="section-head"><h2>Rules it holds itself to</h2></header>
        <ul className="lines">
          <li>Whether content is real and how it spread are separate questions. One never answers the other.</li>
          <li>The earliest appearance found isn't shown to be the source.</li>
          <li>Accounts posting together aren't shown to be coordinating. It looks at timing, shared links, media hashes, matching text and mentions, and it says what's missing.</li>
          <li>An unknown value stays empty with a reason. It's never filled in or shown as zero.</li>
          <li>Invented data is labelled wherever it appears, and says nothing about real bots, intent or who is responsible.</li>
          <li>Nothing leaves this server unless you tick the box that sends it.</li>
        </ul>
      </section>
    </div>
  );
}
