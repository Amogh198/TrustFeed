import { LoaderCircle, TriangleAlert } from 'lucide-react';
import type { ReactNode } from 'react';
import { safeHttpUrl } from '../api.js';
import { scoreText, utc } from '../lib/format';
import type { TimelineEvent } from '../types';

/** The three kinds of information in a report. Each one looks different everywhere it appears. */
export type Kind = 'observed' | 'estimate' | 'unknown';

const KIND_WORDS: Record<Kind, string> = {
  observed: 'Observed',
  estimate: 'Estimate',
  unknown: 'Not known',
};

export function KindTag({ kind }: { kind: Kind }) {
  return <span className={`kind kind-${kind}`}><i aria-hidden="true" />{KIND_WORDS[kind]}</span>;
}

export function Section({ title, kind, lead, children, id }: {
  title: string; kind?: Kind; lead?: ReactNode; children: ReactNode; id?: string;
}) {
  return (
    <section className="section" id={id}>
      <header className="section-head">
        <h2>{title}</h2>
        {kind && <KindTag kind={kind} />}
      </header>
      {lead && <p className="lead">{lead}</p>}
      {children}
    </section>
  );
}

/** A score. Hatched because it is an estimate, and empty rather than zero when nothing was measured. */
export function Meter({ value, label }: { value: number | null | undefined; label?: string }) {
  if (value == null) {
    return <div className="meter meter-none"><span className="meter-track" aria-hidden="true" /><b>No score</b></div>;
  }
  const percent = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="meter">
      <span className="meter-track" aria-hidden="true"><span style={{ width: `${percent}%` }} /></span>
      <b>{label ? `${label} ` : ''}{scoreText(value)}</b>
    </div>
  );
}

/** Hazard tape: anything invented or replayed carries it wherever it appears. */
export function Tape({ children }: { children: ReactNode }) {
  return <p className="tape"><span>{children}</span></p>;
}

export function Unknown({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="unknown">
      {title && <strong>{title}</strong>}
      <div>{children}</div>
    </div>
  );
}

export function Caveat({ children }: { children: ReactNode }) {
  return <div className="caveat"><TriangleAlert size={17} aria-hidden="true" /><div>{children}</div></div>;
}

/** Only http and https become links. Titles and handles are never trusted, and stay plain text. */
export function SafeLink({ href, children }: { href: string | null | undefined; children: ReactNode }) {
  const safe = safeHttpUrl(href);
  return safe ? <a href={safe} target="_blank" rel="noreferrer noopener">{children}</a> : <span>{children}</span>;
}

export function Lines({ items, className }: { items: string[]; className?: string }) {
  return <ul className={className || 'lines'}>{items.map((item, index) => <li key={index}>{item}</li>)}</ul>;
}

export function Limits({ items, title = "What it can't show", open }: { items: string[]; title?: string; open?: boolean }) {
  if (!items?.length) return null;
  return (
    <details className="limits" open={open}>
      <summary>{title} ({items.length})</summary>
      <Lines items={items} />
    </details>
  );
}

export function Loading({ children }: { children: ReactNode }) {
  return <p className="loading" role="status"><LoaderCircle className="spin" size={17} aria-hidden="true" />{children}</p>;
}

export function Problem({ children }: { children: ReactNode }) {
  return <p className="problem" role="alert">{children}</p>;
}

export function Figure({ value, label, small }: { value: ReactNode; label: string; small?: string }) {
  return (
    <div className="figure">
      <b>{value}</b>
      <span>{label}</span>
      {small && <small>{small}</small>}
    </div>
  );
}

const EVENT_KINDS: Record<string, string> = {
  web_appearance: 'Web page',
  social_post: 'Public post',
  cluster_activity: 'Flagged group activity',
};

function EventRow({ event }: { event: TimelineEvent }) {
  return (
    <li className={`event event-${event.kind}`}>
      <time>{event.at ? utc(event.at) : 'No date'}</time>
      <div>
        <strong>{event.label}</strong>
        <span>{EVENT_KINDS[event.kind] || event.kind}{event.synthetic ? ', synthetic' : ''}</span>
      </div>
    </li>
  );
}

/** Undated events stay visible in their own group and never get an invented date. */
export function EventList({ events }: { events: TimelineEvent[] }) {
  const dated = events.filter(event => event.at);
  const undated = events.filter(event => !event.at);
  return (
    <>
      {dated.length > 0 && <ol className="events">{dated.map((event, index) => <EventRow key={`${event.ref}-${index}`} event={event} />)}</ol>}
      {undated.length > 0 && (
        <Unknown title={`Undated (${undated.length})`}>
          <ol className="events">{undated.map((event, index) => <EventRow key={`${event.ref}-${index}`} event={event} />)}</ol>
        </Unknown>
      )}
    </>
  );
}
