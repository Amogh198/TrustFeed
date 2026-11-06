import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { Loading, Problem } from '../ui/ui';

type Cell = string | { text: string; url: string };
type Block =
  | { type: 'text'; text: string }
  | { type: 'list'; items: string[] }
  | { type: 'kv'; rows: { label: string; value: Cell; copy?: boolean }[] }
  | { type: 'table'; columns: string[]; rows: Cell[][]; omitted?: number };
type JudgeReport = { sections: { id: string; title: string; blocks: Block[] }[] };

function CellView({ cell }: { cell: Cell }) {
  return typeof cell === 'string' ? <>{cell}</> : <a href={cell.url} target="_blank" rel="noreferrer noopener">{cell.text}</a>;
}

function BlockView({ block }: { block: Block }) {
  if (block.type === 'text') return <p>{block.text}</p>;
  if (block.type === 'list') return <ul className="lines">{block.items.map((item, index) => <li key={index}>{item}</li>)}</ul>;
  if (block.type === 'kv') {
    return (
      <div className="table-scroll">
        <table className="table report-kv">
          <tbody>
            {block.rows.map(row => (
              <tr key={row.label}>
                <th scope="row">{row.label}</th>
                <td className={row.copy ? 'mono' : undefined}>
                  <CellView cell={row.value} />
                  {row.copy && typeof row.value === 'string' && row.value !== 'Not recorded' && (
                    <button type="button" className="link-button no-print report-copy" onClick={() => navigator.clipboard?.writeText(row.value as string)}>Copy</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <div className="table-scroll">
      <table className="table">
        <thead><tr>{block.columns.map(column => <th key={column}>{column}</th>)}</tr></thead>
        <tbody>{block.rows.map((row, index) => <tr key={index}>{row.map((cell, inner) => <td key={inner}><CellView cell={cell} /></td>)}</tr>)}</tbody>
      </table>
      {!!block.omitted && <p className="fineprint">{block.omitted} more rows are left out here.</p>}
    </div>
  );
}

/** Draws the sections the server builds. The PDF draws the same ones, so the two can't disagree. */
export default function ReportTab({ caseId }: { caseId: string }) {
  const [report, setReport] = useState<JudgeReport | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    api.getReport(caseId).then(result => { if (live) setReport(result); }).catch(problem => { if (live) setError(problem.message); });
    return () => { live = false; };
  }, [caseId]);
  if (error) return <Problem>{error}</Problem>;
  if (!report) return <Loading>Building the report</Loading>;
  return (
    <div className="report">
      {report.sections.map(section => (
        <section key={section.id} id={section.id} className="report-section">
          <h2>{section.title}</h2>
          {section.blocks.map((block, index) => <BlockView key={index} block={block} />)}
        </section>
      ))}
    </div>
  );
}
