import { caseHref } from '../lib/route';

const STEPS: { title: string; say: string; do: string; href: string; link: string }[] = [
  {
    title: 'Check a real file',
    say: 'Any image or video goes in. The model gives a signal, never a verdict, and the report shows how that model did when tested.',
    do: 'Upload an image, open the Media tab, and make a heatmap.',
    href: '#/',
    link: 'Open the check form',
  },
  {
    title: 'Check a post with a link',
    say: 'The text is split into claims and the words that set off a rule are marked. Every claim stays unverified, because nothing outside was consulted.',
    do: 'Open the Text and link tab.',
    href: caseHref('demo-story-001', 'text'),
    link: 'Open the dam rumour',
  },
  {
    title: 'See where an image has been',
    say: 'Source search lists where the image was found. The earliest page found is not called the source, and the report says why.',
    do: 'Point at the caveat above the list of pages.',
    href: caseHref('demo-001', 'source'),
    link: 'Open the source search',
  },
  {
    title: 'Replay the spread',
    say: 'Sharp spikes are groups of accounts posting the same items within two minutes. The flat trickle after them is ordinary sharing. This is a signal to review, not proof.',
    do: 'Press Play, then Next burst, then Find the earliest account.',
    href: caseHref('demo-001', 'spread'),
    link: 'Open the 320-account spread',
  },
  {
    title: 'Show why earliest is not origin',
    say: "In this story the earliest post is outside the flagged group, so being first doesn't make an account the source. The table also shows what wasn't searched.",
    do: 'Find the earliest account, then scroll to Where this looked.',
    href: caseHref('demo-story-001', 'spread'),
    link: 'Open the story trace',
  },
  {
    title: 'Close with what to do',
    say: 'The packet turns the evidence into steps and a correction draft. It comes from fixed rules, so a person confirms it before anyone uses it.',
    do: 'Change who the draft is for, then copy the correction card.',
    href: caseHref('demo-story-001', 'action'),
    link: 'Open the action packet',
  },
];

export default function Walkthrough() {
  return (
    <div className="page">
      <header className="page-head">
        <h1>Demo walkthrough</h1>
        <p>Six steps for about three minutes. Every step except the first uses invented data, runs with no internet, and is labelled on screen.</p>
      </header>
      <ol className="steps">
        {STEPS.map(step => (
          <li key={step.title}>
            <h2>{step.title}</h2>
            <p>{step.say}</p>
            <p className="step-do"><strong>Do this: </strong>{step.do}</p>
            <a className="button" href={step.href}>{step.link}</a>
          </li>
        ))}
      </ol>
      <p className="fineprint">Before you go on stage, have the API running and open <a href="#/limits">what it covers and misses</a> in a spare tab, for questions.</p>
    </div>
  );
}
