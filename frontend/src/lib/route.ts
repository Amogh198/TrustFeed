import { useEffect, useState } from 'react';

export type Route =
  | { page: 'home' }
  | { page: 'overview' }
  | { page: 'cases' }
  | { page: 'watch' }
  | { page: 'walkthrough' }
  | { page: 'limits' }
  | { page: 'case'; caseId: string; tab: string };

export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  if (parts[0] === 'case' && parts[1]) {
    return { page: 'case', caseId: decodeURIComponent(parts[1]), tab: parts[2] || 'findings' };
  }
  if (parts[0] === 'overview' || parts[0] === 'cases' || parts[0] === 'watch' || parts[0] === 'walkthrough' || parts[0] === 'limits') {
    return { page: parts[0] };
  }
  return { page: 'home' };
}

export function caseHref(caseId: string, tab?: string): string {
  return `#/case/${encodeURIComponent(caseId)}${tab ? `/${tab}` : ''}`;
}

export function go(href: string): void {
  window.location.hash = href;
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const update = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  return route;
}
