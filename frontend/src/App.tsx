import { useEffect, useState } from 'react';
import { api, API_BASE_URL } from './api.js';
import CaseFile from './case/CaseFile';
import { useRoute } from './lib/route';
import type { AccountState } from './types';
import Account from './pages/Account';
import Cases from './pages/Cases';
import Home from './pages/Home';
import Limits from './pages/Limits';
import Overview from './pages/Overview';
import Walkthrough from './pages/Walkthrough';
import Watch from './pages/Watch';
import ErrorBoundary from './ui/ErrorBoundary';

const NAV: [string, string, string][] = [
  ['home', '#/', 'Check'],
  ['overview', '#/overview', 'Overview'],
  ['cases', '#/cases', 'Cases'],
  ['watch', '#/watch', 'Watch'],
  ['walkthrough', '#/walkthrough', 'Walkthrough'],
  ['limits', '#/limits', 'What it misses'],
];

function useApiHealth(): boolean | null {
  const [online, setOnline] = useState<boolean | null>(null);
  useEffect(() => {
    let live = true;
    const check = () => api.health().then(() => live && setOnline(true)).catch(() => live && setOnline(false));
    check();
    const timer = window.setInterval(check, 10_000);
    return () => { live = false; window.clearInterval(timer); };
  }, []);
  return online;
}

export default function App() {
  const route = useRoute();
  const online = useApiHealth();
  const [account, setAccount] = useState<AccountState | null>(null);
  useEffect(() => { api.getAccount().then(setAccount).catch(() => setAccount(null)); }, []);
  const mustSignIn = Boolean(account?.auth_required && !account.email);
  const caseKey = route.page === 'case' ? route.caseId : route.page;

  useEffect(() => { window.scrollTo(0, 0); }, [caseKey]);

  return (
    <>
      <a className="skip" href="#main">Skip to the content</a>
      <header className="topbar no-print">
        <a className="brand" href="#/" aria-label="TrustFeed, home">
          <svg viewBox="0 0 32 32" width="22" height="22" aria-hidden="true">
            <path d="M6 25 15 15l11-8" stroke="#ff4f8b" strokeWidth="2.5" fill="none" />
            <circle cx="6" cy="25" r="3.5" fill="#eef25a" />
            <circle cx="15" cy="15" r="3" fill="#ff4f8b" />
            <circle cx="26" cy="7" r="3" fill="#ff4f8b" />
          </svg>
          TrustFeed
        </a>
        <nav aria-label="Main">
          {NAV.map(([page, href, name]) => (
            <a key={page} href={href} aria-current={route.page === page ? 'page' : undefined}>{name}</a>
          ))}
          <a href="#/account" aria-current={route.page === 'account' ? 'page' : undefined}>{account?.email ? 'Account' : 'Sign in'}</a>
        </nav>
        <span className={`health health-${online === null ? 'wait' : online ? 'on' : 'off'}`} role="status">
          {online === null ? 'Looking for the API' : online ? 'API running' : 'API not running'}
        </span>
      </header>
      {online === false && (
        <div className="offline no-print" role="alert">
          <strong>The API isn't answering at {API_BASE_URL}.</strong> From the repository root, run <code>python -m uvicorn backend.api.app.main:app</code>. This page reconnects by itself.
        </div>
      )}
      <main id="main">
        <ErrorBoundary resetKey={window.location.hash}>
          {mustSignIn && <Account account={account} />}
          {!mustSignIn && route.page === 'account' && <Account account={account} />}
          {!mustSignIn && route.page === 'home' && <Home />}
          {!mustSignIn && route.page === 'overview' && <Overview />}
          {!mustSignIn && route.page === 'cases' && <Cases />}
          {!mustSignIn && route.page === 'watch' && <Watch />}
          {!mustSignIn && route.page === 'walkthrough' && <Walkthrough />}
          {!mustSignIn && route.page === 'limits' && <Limits />}
          {!mustSignIn && route.page === 'case' && <CaseFile key={route.caseId} caseId={route.caseId} tab={route.tab} />}
        </ErrorBoundary>
      </main>
    </>
  );
}
