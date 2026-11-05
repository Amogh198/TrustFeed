import { Radar, Square } from 'lucide-react';
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { api, ApiError } from '../api.js';
import { CoverageTable, PostList } from '../case/Coverage';
import SpreadStage from '../graph/SpreadStage';
import { platformName, utc } from '../lib/format';
import type { Coverage, NetworkPayload, WatchSnapshot } from '../types';
import { Caveat, Figure, Loading, Problem, Section, Unknown } from '../ui/ui';

const POLL_GAP_SECONDS = 60;

function splitList(value: string): string[] {
  return value.split(/[\s,]+/).map(item => item.trim()).filter(Boolean);
}

export default function Watch() {
  const [text, setText] = useState('');
  const [links, setLinks] = useState('');
  const [hashtags, setHashtags] = useState('');
  const [consent, setConsent] = useState(false);
  const [watchId, setWatchId] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<WatchSnapshot | null>(null);
  const [graph, setGraph] = useState<NetworkPayload | null>(null);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState('');
  const [running, setRunning] = useState<string[]>([]);
  const [wait, setWait] = useState(0);

  const loadRunning = useCallback(async () => {
    try { setRunning((await api.listMonitors()).watches); } catch { setRunning([]); }
  }, []);
  useEffect(() => { loadRunning(); }, [loadRunning]);

  useEffect(() => {
    if (wait <= 0) return undefined;
    const timer = window.setTimeout(() => setWait(value => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [wait]);

  const poll = async (id: string) => {
    setWorking(true);
    setMessage('');
    try {
      setSnapshot(await api.pollMonitor(id));
      setWait(POLL_GAP_SECONDS);
      const [nextGraph, nextCoverage] = await Promise.all([api.getNetwork(id), api.getCoverage(id)]);
      setGraph(nextGraph);
      setCoverage(nextCoverage);
    } catch (error) {
      if (error instanceof ApiError && error.status === 429) setWait(POLL_GAP_SECONDS);
      if (error instanceof ApiError && error.status === 404) {
        setWatchId(null);
        loadRunning();
      }
      setMessage((error as Error).message);
    } finally { setWorking(false); }
  };

  const start = async (event: FormEvent) => {
    event.preventDefault();
    const urls = splitList(links);
    const tags = splitList(hashtags).map(tag => tag.replace(/^#/, ''));
    if (!text.trim() && !urls.length && !tags.length) return setMessage('Add text, a link or a hashtag to watch.');
    if (!consent) return setMessage('Tick the box first. Watching sends these terms to outside services.');
    if (urls.length > 5 || tags.length > 5) return setMessage('A watch takes up to 5 links and 5 hashtags.');
    setMessage('');
    setWorking(true);
    try {
      const started = await api.startMonitor({ opted_in: true, text: text.trim() || null, urls, hashtags: tags });
      setWatchId(started.watch_id);
      setSnapshot(null);
      await poll(started.watch_id);
      loadRunning();
    } catch (error) { setMessage((error as Error).message); setWorking(false); }
    return undefined;
  };

  const resume = (id: string) => {
    setWatchId(id);
    setSnapshot(null);
    setGraph(null);
    setCoverage(null);
    poll(id);
  };

  const stop = async (id: string) => {
    await api.stopMonitor(id).catch(() => null);
    if (id === watchId) {
      setWatchId(null);
      setSnapshot(null);
      setGraph(null);
      setCoverage(null);
      setMessage('Watch stopped. Nothing further will be sent.');
    }
    loadRunning();
  };

  const newCount = snapshot ? Object.values(snapshot.new_posts || {}).reduce((sum, count) => sum + count, 0) : 0;

  return (
    <div className="page page-wide">
      <header className="page-head">
        <h1>Watch public platforms</h1>
        <p>Search a topic again whenever you choose, and see what's new. This polls public search, so it isn't a complete feed of any platform. Nothing runs in the background.</p>
      </header>

      {message && <Problem>{message}</Problem>}

      {!watchId && running.length > 0 && (
        <Section title="Watches still open" lead="These send nothing unless you poll them, and they end after 24 hours.">
          <ul className="watch-list">
            {running.map(id => (
              <li key={id}>
                <span className="mono">{id.slice(0, 24)}</span>
                <button type="button" className="button button-small" onClick={() => resume(id)}>Poll this watch</button>
                <button type="button" className="button button-small" onClick={() => stop(id)}>Stop</button>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {!watchId && (
        <form className="watch-form" onSubmit={start}>
          <label className="field">Text to watch
            <textarea value={text} onChange={event => setText(event.target.value)} maxLength={2000} rows={3} placeholder="A distinctive sentence from the post" />
          </label>
          <div className="watch-fields">
            <label className="field">Links, separated by spaces
              <input value={links} onChange={event => setLinks(event.target.value)} placeholder="https://example.org/story" />
            </label>
            <label className="field">Hashtags, separated by spaces
              <input value={hashtags} onChange={event => setHashtags(event.target.value)} placeholder="#floods" />
            </label>
          </div>
          <label className="consent">
            <input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} />
            <span>
              <strong>Send these terms to public platform search</strong>
              <small>Required. They go to the search services of Mastodon, Lemmy, Hacker News and Bluesky each time you poll. A watch ends after 24 hours, and you can have up to 5.</small>
            </span>
          </label>
          <button type="submit" className="button button-primary button-large" disabled={working}>
            <Radar size={17} aria-hidden="true" />{working ? 'Searching, up to 25 seconds' : 'Start watching'}
          </button>
        </form>
      )}

      {watchId && (
        <section className="watch-live">
          <header>
            <div>
              <h2>Watch open</h2>
              <p className="fineprint">{snapshot ? `Poll ${snapshot.poll}, ${utc(snapshot.polled_at)}` : 'Waiting for the first poll'}</p>
            </div>
            <div className="watch-actions">
              <button type="button" className="button button-primary" disabled={working || wait > 0} onClick={() => poll(watchId)}>
                <Radar size={16} aria-hidden="true" />{working ? 'Searching' : wait > 0 ? `Poll again in ${wait} s` : 'Poll now'}
              </button>
              <button type="button" className="button" onClick={() => stop(watchId)}><Square size={15} aria-hidden="true" />Stop</button>
            </div>
          </header>
          {working && !snapshot && <Loading>Searching the connected platforms, up to 25 seconds</Loading>}
          {snapshot && (
            <>
              <div className="figures">
                <Figure value={snapshot.total_matching_posts} label="matching posts" />
                <Figure value={newCount} label="new this poll" />
                <Figure value={snapshot.platforms_read.length} label="platforms read" small={snapshot.platforms_read.map(platformName).join(', ') || 'None'} />
              </div>
              {snapshot.alerts.length > 0
                ? <Caveat><strong>Alerts for review</strong><ul className="lines">{snapshot.alerts.map((alert, index) => <li key={index}>{alert.message}</li>)}</ul></Caveat>
                : <Unknown>No alerts on this poll. That doesn't show nothing is happening.</Unknown>}
            </>
          )}
        </section>
      )}

      {watchId && graph?.nodes?.length ? <SpreadStage graph={graph} /> : null}
      {watchId && coverage && (
        <>
          <CoverageTable coverage={coverage} />
          <PostList coverage={coverage} />
        </>
      )}
    </div>
  );
}
