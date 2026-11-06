import { useState, type FormEvent } from 'react';
import { api } from '../api.js';
import type { AccountState } from '../types';
import { Problem } from '../ui/ui';

/** Sign in or create an account. Reloads afterwards, so nothing from the last person stays on screen. */
export default function Account({ account }: { account: AccountState | null }) {
  const [mode, setMode] = useState<'login' | 'signup'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [message, setMessage] = useState('');
  const [working, setWorking] = useState(false);
  const canSignUp = account?.signup_enabled !== false;

  const finish = () => {
    window.location.hash = '#/cases';
    window.location.reload();
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setMessage('');
    setWorking(true);
    try {
      await (mode === 'login' ? api.login(email, password) : api.signup(email, password));
      finish();
    } catch (problem) {
      setMessage((problem as Error).message);
      setWorking(false);
    }
  };

  const signOut = async () => {
    try {
      await api.logout();
      window.location.hash = '#/';
      window.location.reload();
    } catch (problem) {
      setMessage((problem as Error).message);
    }
  };

  if (account?.email) {
    return (
      <div className="page page-narrow">
        <header className="page-head">
          <h1>Your account</h1>
          <p>Signed in as <strong>{account.email}</strong>. Your saved cases are visible only to you.</p>
        </header>
        {message && <Problem>{message}</Problem>}
        <button type="button" className="button" onClick={signOut}>Sign out</button>
      </div>
    );
  }

  return (
    <div className="page page-narrow">
      <header className="page-head">
        <h1>{mode === 'login' ? 'Sign in' : 'Create an account'}</h1>
        <p>
          {account?.auth_required
            ? 'This server needs an account before it checks anything.'
            : 'Cases you check while signed in are visible only to you. Cases checked while signed out are shared with anyone else signed out on this server.'}
        </p>
      </header>
      <form className="account-form" onSubmit={submit}>
        <label className="field">Email
          <input type="email" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} />
        </label>
        <label className="field">Password
          <input
            type="password"
            required
            minLength={mode === 'signup' ? 10 : undefined}
            maxLength={200}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            value={password}
            onChange={event => setPassword(event.target.value)}
          />
        </label>
        {mode === 'signup' && <p className="fineprint">At least 10 characters. There's no password reset yet, so keep it somewhere safe.</p>}
        {message && <Problem>{message}</Problem>}
        <button type="submit" className="button button-primary" disabled={working}>{mode === 'login' ? 'Sign in' : 'Create account'}</button>
      </form>
      {canSignUp && (
        <p className="fineprint">
          <button type="button" className="link-button" onClick={() => { setMode(mode === 'login' ? 'signup' : 'login'); setMessage(''); }}>
            {mode === 'login' ? 'Need an account? Create one' : 'Have an account? Sign in'}
          </button>
        </p>
      )}
    </div>
  );
}
