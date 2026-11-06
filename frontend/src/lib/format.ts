import type { AnalysisResponse, Benchmark, RiskLevel } from '../types';

export const MODULE_ORDER = ['media', 'text', 'url', 'provenance', 'network'] as const;

export const MODULE_NAMES: Record<string, string> = {
  media: 'Media',
  text: 'Text',
  url: 'Link',
  provenance: 'Source search',
  network: 'Spread',
};

export const RISK_LEVELS: RiskLevel[] = ['critical', 'high', 'moderate', 'low', 'inconclusive'];

export const STATUS_WORDS: Record<string, string> = {
  complete: 'Ran',
  unavailable: "Didn't run",
  not_applicable: 'Not needed',
};

/** A null score means nothing was measured. It must never read as zero. */
export function scoreText(value: number | null | undefined): string {
  return value == null ? 'No score' : value.toFixed(2);
}

export function confidenceText(value: number | null | undefined): string {
  return value == null ? 'Confidence not measured' : `Confidence ${value.toFixed(2)}`;
}

/** Evidence times are shown in UTC so that two people reading one report see the same time. */
export function utc(value: string | null | undefined): string {
  if (!value) return 'No date';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.toLocaleString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC',
  })} UTC`;
}

export function utcClock(ms: number): string {
  return `${new Date(ms).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'UTC' })} UTC`;
}

export function words(value: string | null | undefined): string {
  if (!value) return 'Unknown';
  const text = value.replaceAll('_', ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const PLATFORM_NAMES: Record<string, string> = {
  mastodon: 'Mastodon',
  lemmy: 'Lemmy',
  hackernews: 'Hacker News',
  hacker_news: 'Hacker News',
  bluesky: 'Bluesky',
  x: 'X',
  youtube: 'YouTube',
  reddit: 'Reddit',
  demo_microblog: 'Demo microblog (synthetic)',
  demo_forum: 'Demo forum (synthetic)',
  demo_news: 'Demo news board (synthetic)',
  demo_video: 'Demo video site (synthetic)',
};

export function platformName(value: string): string {
  return PLATFORM_NAMES[value] || words(value);
}

export const MATCH_WORDING: Record<string, string> = {
  link: 'Carries the submitted link',
  page_link: 'Links to a page where the image was found, which may be about something else',
  hashtag: 'Uses the hashtag, which shows a shared topic, not shared content',
  text: 'Contains the submitted text',
  image: 'Its picture looks like the submitted file, by fingerprint',
};

// Below this the detector's band is low or inconclusive, and it flags few fakes at these settings.
const MEDIA_ELEVATED = 0.75;

export function isQuietMedia(report: AnalysisResponse): boolean {
  const media = report.modules?.media;
  return media?.status === 'complete' && media.score != null && media.score < MEDIA_ELEVATED;
}

/** Phrases the text rules quoted, such as 'urgent', so they can be marked in the claim. */
export function quotedPhrases(evidence: string[]): string[] {
  const found = new Set<string>();
  for (const line of evidence) {
    for (const match of line.matchAll(/'([^']{2,80})'/g)) found.add(match[1].toLowerCase());
  }
  return [...found];
}

/** Splits text around the phrases. The result is rendered as text, so nothing can inject markup. */
export function markPhrases(text: string, phrases: string[]): { text: string; marked: boolean }[] {
  if (!phrases.length) return [{ text, marked: false }];
  const escaped = [...phrases]
    .sort((a, b) => b.length - a.length)
    .map(phrase => phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const pattern = new RegExp(`(${escaped.join('|')})`, 'gi');
  return text
    .split(pattern)
    .filter(Boolean)
    .map(part => ({ text: part, marked: phrases.includes(part.toLowerCase()) }));
}

export function benchmarkSentence(benchmark: Benchmark | null | undefined): string {
  if (!benchmark) return 'Not measured';
  if (benchmark.results_file && !benchmark.n_fake) return `Measured once on one public set, not for this kind of audio in general. See ${benchmark.results_file}.`;
  const parts: string[] = [];
  if (benchmark.n_fake) parts.push(`Flagged ${benchmark.flagged_fake ?? 0} of ${benchmark.n_fake} fakes`);
  if (benchmark.n_real) parts.push(`wrongly flagged ${benchmark.flagged_real ?? 0} of ${benchmark.n_real} real images`);
  if (benchmark.auc != null) parts.push(`AUC ${benchmark.auc}`);
  return parts.length ? `${parts.join(', ')}, on the benchmark's test set only.` : 'Measured. See the results file.';
}

export function asLines(value: string | string[] | null | undefined): string[] {
  if (Array.isArray(value)) return value;
  return value ? [value] : [];
}

export function fileSize(bytes: number): string {
  return bytes >= 1_048_576 ? `${(bytes / 1_048_576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export const IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
export const VIDEO_TYPES = ['video/mp4', 'video/quicktime', 'video/webm', 'video/x-msvideo'];
export const AUDIO_TYPES = ['audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav', 'audio/wave', 'audio/mp4', 'audio/x-m4a', 'audio/aac', 'audio/flac', 'audio/x-flac', 'audio/ogg', 'audio/webm'];

/** Catches the obvious refusals before an upload starts. The API still checks the file's content. */
export function uploadProblem(file: { type: string; size: number }): string | null {
  const image = IMAGE_TYPES.includes(file.type);
  const video = VIDEO_TYPES.includes(file.type);
  const audio = AUDIO_TYPES.includes(file.type);
  if (!image && !video && !audio) return "That file isn't a supported type. Choose a JPEG, PNG, WebP, MP4, MOV, WebM, AVI, MP3, WAV, M4A, FLAC or OGG file.";
  if (file.size === 0) return 'That file is empty. Choose another one.';
  if (image && file.size > 25 * 1024 * 1024) return 'That image is over the 25 MB limit.';
  if (video && file.size > 200 * 1024 * 1024) return 'That video is over the 200 MB limit.';
  if (audio && file.size > 100 * 1024 * 1024) return 'That audio file is over the 100 MB limit.';
  return null;
}

export function downloadFile(name: string, content: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

export function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

const TRUST_MODULES = ['media', 'text', 'url'] as const;

/** A neutral midpoint, not a measurement. No check here can show that content is genuine. */
export const NEUTRAL_TRUST = 50;
// The same levels the API's risk result uses. They catch signals the model score doesn't hold,
// such as metadata naming a generator or a match on the reference list.
const RISK_CEILING: Partial<Record<RiskLevel, number>> = { moderate: 40, high: 25, critical: 25 };

export interface Trust {
  score: number | null;
  words: string;
  strongest: { name: string; value: number } | null;
  counted: { name: string; value: number }[];
  mediaMissing: boolean;
  /** The checks' own figure was higher, and the midpoint held it down. */
  capped: boolean;
  /** The overall risk result lowered the score, rather than the strongest signal. */
  fromOverallRisk: boolean;
}

/**
 * 100 minus the strongest warning signal from the checks that looked at the content itself,
 * and never above the midpoint: finding no warning isn't evidence that content is genuine.
 * The detector scored 128 of 157 fakes low in testing, so a low score can't earn a high number.
 * Spread and source search aren't counted: where content went doesn't say whether it's true.
 * It's null when nothing was measured, and is never filled in.
 */
export function trustScore(report: AnalysisResponse): Trust {
  // The server's figure counts only measured signals. Cases saved earlier don't have one.
  const unified = report.unified_risk;
  if (unified) {
    const scored = unified.components.filter(item => item.counted && item.score != null).map(item => ({ name: item.label, value: item.score as number }));
    const strongest = scored.length ? scored.reduce((top, item) => (item.value > top.value ? item : top)) : null;
    const value = unified.trust_score;
    const words = value == null
      ? 'No trust score'
      : value >= NEUTRAL_TRUST ? 'Inconclusive: not enough evidence' : value > 25 ? 'Some warning signs' : 'Warning signs found: a person should review this';
    return {
      score: value,
      words,
      strongest,
      counted: scored,
      mediaMissing: report.modules?.media?.status === 'unavailable',
      capped: value === NEUTRAL_TRUST,
      fromOverallRisk: false,
    };
  }
  const counted = TRUST_MODULES.flatMap(key => {
    const module = report.modules?.[key];
    return module?.status === 'complete' && module.score != null ? [{ name: MODULE_NAMES[key], value: module.score }] : [];
  });
  const mediaMissing = report.modules?.media?.status === 'unavailable';
  if (!counted.length) {
    return { score: null, words: 'No trust score', strongest: null, counted, mediaMissing, capped: false, fromOverallRisk: false };
  }
  const strongest = counted.reduce((top, item) => (item.value > top.value ? item : top));
  const measured = Math.round((1 - strongest.value) * 100);
  const ceiling = RISK_CEILING[report.overall_risk] ?? NEUTRAL_TRUST;
  const score = Math.min(measured, NEUTRAL_TRUST, ceiling);
  const words = score >= NEUTRAL_TRUST
    ? 'Inconclusive: not enough evidence'
    : score > 25 ? 'Some warning signs' : 'Warning signs found: a person should review this';
  return { score, words, strongest, counted, mediaMissing, capped: measured > NEUTRAL_TRUST, fromOverallRisk: ceiling < Math.min(measured, NEUTRAL_TRUST) };
}
