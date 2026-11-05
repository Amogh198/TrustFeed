import SpreadStage from '../graph/SpreadStage';
import type { AnalysisResponse, Coverage, NetworkPayload } from '../types';
import { Caveat, Limits, Lines, Loading, Meter, Section, Unknown } from '../ui/ui';
import { CoverageTable, PostList } from './Coverage';

export default function SpreadTab({ report, graph, coverage, loading }: {
  report: AnalysisResponse; graph?: NetworkPayload; coverage?: Coverage | null; loading: boolean;
}) {
  const network = report.modules?.network;
  if (loading && !graph) return <Loading>Laying out the accounts and their links</Loading>;
  const hasGraph = Boolean(graph?.nodes?.length);
  return (
    <>
      {hasGraph && <SpreadStage graph={graph} autoScroll />}
      <div className="panel-inner">
        <Caveat>
          <strong>This is a signal for review. It doesn't prove coordination.</strong>
          <p>Posting the same items close together doesn't show automation, identity, who is behind an account, or intent. Repost timing isn't available, so it isn't used.</p>
        </Caveat>

        {network?.status === 'complete' && (
          <Section title="Why this was flagged" kind="estimate">
            <Meter value={network.score} label="Review signal" />
            <p className="fineprint">A heuristic score out of 1, not a calibrated probability.</p>
            <Lines items={network.evidence} />
            <Limits items={network.limitations} />
          </Section>
        )}

        {coverage ? (
          <>
            <CoverageTable coverage={coverage} />
            <PostList coverage={coverage} />
          </>
        ) : (
          <Section title="Where this looked" kind="unknown">
            <Unknown title="No public-post trace ran for this case">
              <p>{network?.status === 'complete' ? "This case's network comes from synthetic demo data, so no real platform was searched." : network?.limitations?.[0] || 'Nothing was sent to outside platforms.'}</p>
              {network?.status !== 'complete' && <p>To trace it, submit the content again with the search box ticked.</p>}
            </Unknown>
          </Section>
        )}
      </div>
    </>
  );
}
