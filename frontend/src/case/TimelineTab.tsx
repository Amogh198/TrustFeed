import type { TimelineEvent } from '../types';
import { EventList, Loading, Section, Unknown } from '../ui/ui';

export default function TimelineTab({ events, loading }: { events?: TimelineEvent[]; loading: boolean }) {
  if (!events) {
    if (loading) return <Loading>Putting events in order</Loading>;
    return <Unknown title="The timeline didn't load">Reload the page to try again.</Unknown>;
  }
  return (
    <Section
      title="Everything in time order"
      kind="observed"
      lead="Web appearances, matching posts and flagged group activity on one line. The first entry is only the earliest found."
    >
      {events.length
        ? <EventList events={events} />
        : <Unknown>Nothing with a time was saved for this case. No source search or public-post trace ran.</Unknown>}
    </Section>
  );
}
