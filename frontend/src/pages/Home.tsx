import { FileImage, FileVideo, Upload, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type DragEvent, type FormEvent } from 'react';
import { api, ApiError, readableUploadError } from '../api.js';
import SpreadCanvas from '../graph/SpreadCanvas';
import { useReplay } from '../graph/useReplay';
import { fileSize, IMAGE_TYPES, uploadProblem, utc, VIDEO_TYPES } from '../lib/format';
import { buildView } from '../lib/graph';
import { caseHref, go } from '../lib/route';
import { rememberResult } from '../lib/session';
import type { CaseSummary, NetworkPayload, Scenario } from '../types';
import { Problem, Tape } from '../ui/ui';

function HeroGraph() {
  const [graph, setGraph] = useState<NetworkPayload | null>(null);
  const [label, setLabel] = useState('');
  useEffect(() => {
    let live = true;
    Promise.all([api.getNetwork('demo-001'), api.getCase('demo-001')])
      .then(([network, report]) => {
        if (!live) return;
        setGraph(network);
        setLabel(report.replay_label || 'Synthetic demo data');
      })
      .catch(() => undefined);
    return () => { live = false; };
  }, []);
  const view = useMemo(() => buildView(graph), [graph]);
  const { position } = useReplay(13_000, true, view);
  if (!view) return <div className="hero-graph" aria-hidden="true" />;
  const time = view.start + (view.end - view.start) * position;
  return (
    <div className="hero-graph">
      <SpreadCanvas
        view={view} time={time} interactive={false} focusX={0.7}
        label="Animated graph of invented accounts lighting up as they post the same items."
      />
      <div className="hero-graph-caption">
        <Tape>{label}</Tape>
        <p>Each flash is an account joining a group that posts the same items within two minutes. <a href={caseHref('demo-001', 'spread')}>Explore this replay</a></p>
      </div>
    </div>
  );
}

function Working({ file, search, onCancel }: { file: File | null; search: boolean; onCancel: () => void }) {
  const [seconds, setSeconds] = useState(0);
  const [preview, setPreview] = useState<string | null>(null);
  useEffect(() => {
    const timer = window.setInterval(() => setSeconds(value => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!file?.type.startsWith('image/')) return undefined;
    const address = URL.createObjectURL(file);
    setPreview(address);
    return () => URL.revokeObjectURL(address);
  }, [file]);
  const running = [
    file ? 'Running the image model and reading the file metadata' : null,
    file?.type.startsWith('video/') ? 'Sampling keyframes from the video' : null,
    'Checking text and link rules, if you gave any',
    search && file ? 'Searching for where the image appears' : null,
    search ? 'Searching public posts on Mastodon, Lemmy, Hacker News and Bluesky' : null,
  ].filter(Boolean) as string[];
  return (
    <div className="working" role="status">
      {preview && <div className="heatmap-stage scanning working-image"><img src={preview} alt="" /></div>}
      <div>
        <h2>Checking it now</h2>
        <ul className="lines">{running.map(line => <li key={line}>{line}</li>)}</ul>
        <p className="working-time">{Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, '0')} so far. {search ? 'With search on, this can take up to 3 minutes.' : 'This usually takes under a minute.'}</p>
        <button type="button" className="button" onClick={onCancel}>Stop waiting</button>
      </div>
    </div>
  );
}

function Intake() {
  const [text, setText] = useState('');
  const [url, setUrl] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [search, setSearch] = useState(false);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState('');
  const [dragging, setDragging] = useState(false);
  const abort = useRef<AbortController | null>(null);

  const choose = (chosen: File | null | undefined) => {
    if (!chosen) return;
    const problem = uploadProblem(chosen);
    setMessage(problem || '');
    if (!problem) setFile(chosen);
  };

  useEffect(() => {
    const pushed = window.sessionStorage.getItem('trustfeed_investigate_input');
    if (pushed) {
      window.sessionStorage.removeItem('trustfeed_investigate_input');
      if (pushed.startsWith('http://') || pushed.startsWith('https://')) {
        setUrl(pushed);
      } else {
        setText(pushed);
      }
    }
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const cleanText = text.trim();
    const cleanUrl = url.trim();
    if (!file && !cleanText && !cleanUrl) {
      setMessage('Add the post text, a link, or an image or video to check.');
      return;
    }
    setMessage('');
    setWorking(true);
    abort.current = new AbortController();
    const signal = abort.current.signal;
    try {
      const result = file
        ? await api.analyzeMedia({ file, text: cleanText, url: cleanUrl, searchWeb: search, signal })
        : await api.analyze({ text: cleanText, url: cleanUrl, searchWeb: search, signal });
      rememberResult(result, file);
      go(caseHref(result.case_id));
    } catch (error) {
      setMessage(file && error instanceof ApiError && error.detail?.code !== 'offline' && error.detail?.code !== 'cancelled'
        ? readableUploadError(error)
        : (error as Error).message);
    } finally {
      setWorking(false);
    }
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    choose(event.dataTransfer.files?.[0]);
  };

  if (working) return <Working file={file} search={search} onCancel={() => abort.current?.abort()} />;

  const FileIcon = file?.type.startsWith('video/') ? FileVideo : FileImage;

  return (
    <form
      className={dragging ? 'intake is-dragging' : 'intake'}
      noValidate
      onSubmit={submit}
      onDragOver={event => { event.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <label className="field">Post text
        <textarea className="textarea resize-none" value={text} onChange={event => setText(event.target.value)} maxLength={20000} rows={2} placeholder="Paste the post, caption or forwarded message" />
      </label>
      <label className="field">Link
        <input type="url" value={url} onChange={event => setUrl(event.target.value)} placeholder="https://example.org/post" />
      </label>
      {file ? (
        <div className="file-chosen">
          <FileIcon size={18} aria-hidden="true" />
          <span><strong>{file.name}</strong> {fileSize(file.size)}</span>
          <button type="button" className="text-button" onClick={() => setFile(null)} aria-label="Remove the file"><X size={16} aria-hidden="true" /></button>
        </div>
      ) : (
        <label className="drop">
          <Upload size={18} aria-hidden="true" />
          <span>Drop an image or video, or <u>choose a file</u></span>
          <small>Images up to 25 MB, videos up to 200 MB</small>
          <input type="file" accept={[...IMAGE_TYPES, ...VIDEO_TYPES].join(',')} onChange={event => choose(event.target.files?.[0])} />
        </label>
      )}
      <label className="consent">
        <input type="checkbox" checked={search} onChange={event => setSearch(event.target.checked)} />
        <span>
          <strong>Also search the public web and platforms</strong>
          <small>Off unless you tick it. Sends an uploaded image to the source search services set up on this server, and sends the text and links to Mastodon, Lemmy, Hacker News and Bluesky search. Known short links are followed to their destination.</small>
        </span>
      </label>
      {message && <Problem>{message}</Problem>}
      <button type="submit" className="button button-primary button-large">Check it</button>
    </form>
  );
}

function Demos({ scenarios, onReplay, replayError }: { scenarios: Scenario[]; onReplay: (id: string) => void; replayError: string }) {
  return (
    <div className="demos">
      <p>Or open a demo. All of these use invented data and work with no internet:</p>
      <div className="demo-links">
        <a className="button" href={caseHref('demo-story-001')}>Dam failure rumour</a>
        <a className="button" href={caseHref('demo-001', 'spread')}>320-account spread</a>
        {scenarios.map(scenario => (
          <button key={scenario.id} type="button" className="button" title={scenario.label} onClick={() => onReplay(scenario.id)}>{scenario.title}</button>
        ))}
        <a className="text-link" href="#/walkthrough">Follow the demo walkthrough</a>
      </div>
      {replayError && <Problem>{replayError}</Problem>}
    </div>
  );
}

function Recent({ cases }: { cases: CaseSummary[] }) {
  return (
    <section className="recent">
      <h2>Recent cases</h2>
      {cases.length ? (
        <ol>
          {cases.map(item => (
            <li key={item.case_id}>
              <a href={caseHref(item.case_id)}>
                <span className={`risk risk-${item.overall_risk}`}>{item.overall_risk}</span>
                <span className="recent-summary">{item.summary}</span>
                <span className="recent-time">{utc(item.created_at)}{item.is_replay ? ', replay' : ''}</span>
              </a>
            </li>
          ))}
        </ol>
      ) : <p>Nothing saved yet. Check something above, or open a demo.</p>}
      <a className="text-link" href="#/cases">See all saved cases</a>
    </section>
  );
}

function Watching() {
  return (
    <section className="watching">
      <h2>What it can see</h2>
      <p>When you ask, it reads public search on these platforms. It doesn't run in the background, and it isn't a complete feed of any of them.</p>
      <ul className="platforms">
        {['Mastodon', 'Lemmy', 'Hacker News', 'Bluesky'].map(name => <li key={name} className="on">{name}</li>)}
        {['Reddit', 'YouTube', 'X', 'Private channels'].map(name => <li key={name} className="off">{name}</li>)}
      </ul>
      <p className="fineprint">Dashed platforms aren't connected. <a href="#/limits">See everything it covers and misses</a></p>
    </section>
  );
}

export default function Home() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [replayError, setReplayError] = useState('');
  useEffect(() => {
    let live = true;
    api.getReplayScenarios().then(data => { if (live) setScenarios(data.scenarios); }).catch(() => undefined);
    api.getHistory('', 5).then(data => { if (live) setCases(data.cases); }).catch(() => undefined);
    return () => { live = false; };
  }, []);

  const startReplay = async (id: string) => {
    setReplayError('');
    try {
      const result = await api.startReplay(id);
      rememberResult(result);
      go(caseHref(result.case_id));
    } catch (error) { setReplayError((error as Error).message); }
  };

  return (
    <>
      <div className="hero">
        <HeroGraph />
        <div className="hero-copy">
          <h1>Check a post before it spreads further</h1>
          <p className="hero-lead">Give it the text, link, image or video. You get the evidence, its limits, how the content spread and what to do next. Results are signals for a person to review, not proof.</p>
          <Intake />
          <Demos scenarios={scenarios} onReplay={startReplay} replayError={replayError} />
        </div>
      </div>
      <div className="home-below">
        <Recent cases={cases} />
        <Watching />
      </div>
    </>
  );
}
