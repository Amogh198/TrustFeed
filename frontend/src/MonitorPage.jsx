import React, { useState } from 'react';
import { LoaderCircle, Radar, Square } from 'lucide-react';
import { api } from './api.js';
import NetworkPanel from './NetworkPanel.jsx';

function splitList(value) {
  return value.split(/[\s,]+/).map(item => item.trim()).filter(Boolean);
}

export default function MonitorPage() {
  const [text, setText] = useState('');
  const [links, setLinks] = useState('');
  const [hashtags, setHashtags] = useState('');
  const [consent, setConsent] = useState(false);
  const [watchId, setWatchId] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const [graph, setGraph] = useState(null);
  const [coverage, setCoverage] = useState(null);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState('');

  async function refreshSpread(id) {
    const [nextGraph, nextCoverage] = await Promise.all([api.getNetwork(id), api.getCoverage(id)]);
    setGraph(nextGraph);
    setCoverage(nextCoverage);
  }

  async function poll(id = watchId) {
    setWorking(true);
    setMessage('Searching the connected public platforms. This can take up to about 25 seconds.');
    try {
      setSnapshot(await api.pollMonitor(id));
      await refreshSpread(id);
      setMessage('');
    } catch (error) { setMessage(error.message); } finally { setWorking(false); }
  }

  async function start(event) {
    event.preventDefault();
    const urls = splitList(links);
    const tags = splitList(hashtags).map(tag => tag.replace(/^#/, ''));
    if (!consent) return setMessage('Monitoring sends these terms to outside services, so please tick the box first.');
    if (!text.trim() && !urls.length && !tags.length) return setMessage('Add text, a link or a hashtag to watch.');
    setWorking(true);
    try {
      const started = await api.startMonitor({ opted_in: true, text: text.trim() || null, urls, hashtags: tags });
      setWatchId(started.watch_id);
      await poll(started.watch_id);
    } catch (error) { setMessage(error.message); setWorking(false); }
    return undefined;
  }

  async function stop() {
    await api.stopMonitor(watchId).catch(() => null);
    setWatchId(null);
    setMessage('Monitoring stopped. Nothing further will be sent.');
  }

  return <><header className="page-title"><div><span className="eyebrow">MONITORING</span><h1>Watch public platforms</h1><p>Search a topic again whenever you choose, and see what is new. This polls public search. It is not a complete feed of any platform.</p></div></header>
    {!watchId && !snapshot ? <section className="panel intake"><form onSubmit={start} className="intake">
      <label>Text to watch<textarea value={text} onChange={event => setText(event.target.value)} maxLength="2000" rows="3" placeholder="A distinctive sentence from the post…" /></label>
      <label>Links, separated by spaces<input value={links} onChange={event => setLinks(event.target.value)} placeholder="https://example.org/story" /></label>
      <label>Hashtags, separated by spaces<input value={hashtags} onChange={event => setHashtags(event.target.value)} placeholder="floods" /></label>
      <label className="consent"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} /><span><strong>Send these terms to public platform search</strong><small>Required. They go to the search services of Mastodon, Lemmy, Hacker News and Bluesky each time you poll. Nothing runs in the background, and a watch ends after 24 hours.</small></span></label>
      {message && <div className="notice" aria-live="polite">{message}</div>}
      <button className="button primary" type="submit" disabled={working}>{working ? <LoaderCircle className="spin" size={15} /> : <Radar size={15} />} Start watching</button>
    </form></section> : <>
      {message && <div className="notice" aria-live="polite">{working && <LoaderCircle className="spin" size={15} />}{message}</div>}
      <section className="panel detail-panel"><div className="panel-title"><div><h2>{watchId ? 'Watch running' : 'Watch stopped'}</h2><p>{snapshot ? `Poll ${snapshot.poll} at ${snapshot.polled_at}` : 'Waiting for the first poll'}</p></div>{watchId && <div className="monitor-actions"><button type="button" className="button secondary" disabled={working} onClick={() => poll()}><Radar size={15} /> Poll now</button><button type="button" className="button secondary" onClick={stop}><Square size={15} /> Stop</button></div>}</div>
        {snapshot && <><div className="metric-row"><article className="metric panel"><span>Matching posts</span><strong>{snapshot.total_matching_posts}</strong></article><article className="metric panel"><span>Platforms read</span><strong>{snapshot.platforms_read.length}</strong><small>{snapshot.platforms_read.join(', ') || 'None'}</small></article><article className="metric panel"><span>New this poll</span><strong>{Object.values(snapshot.new_posts).reduce((sum, count) => sum + count, 0)}</strong></article></div>
          {snapshot.alerts.length ? <div className="monitor-alerts"><h3>Alerts for review</h3>{snapshot.alerts.map((alert, index) => <p className="warning" key={index}>{alert.message}</p>)}</div> : <p className="graph-count">No alerts on this poll. That does not show nothing is happening.</p>}</>}
      </section>
      {snapshot && <NetworkPanel graph={graph} coverage={coverage} loading={false} />}
    </>}
  </>;
}
