interface HeatmapRow {
  severity: string;
  sast: number;
  dast: number;
  sca: number;
  iast: number;
}

interface RiskHeatmapProps {
  matrix: HeatmapRow[];
  totals?: Record<string, number>;
}

const SEVERITY_ORDER = ['Critical', 'High', 'Medium', 'Low'];
const TECH_COLS = ['sast', 'dast', 'sca', 'iast'];

/**
 * Severity weights used for risk scoring.
 * Risk Score = issue count × weight.
 * This ensures that a smaller number of Critical issues still registers
 * as higher risk than a larger number of Low issues.
 */
const SEVERITY_WEIGHTS: Record<string, number> = {
  Critical: 4,
  High: 3,
  Medium: 2,
  Low: 1,
};

/** Compute the p-th percentile (0–100) of a sorted array. */
function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  const idx = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

/**
 * Map a risk score to a heat color using percentile thresholds derived from
 * the full risk-score distribution (count × severity weight).
 * Raw issue counts are displayed in cells; color encodes relative risk.
 */
function getHeatColor(riskScore: number, thresholds: [number, number, number]): string {
  if (riskScore === 0) return 'var(--panel)';
  const [p33, p66, p90] = thresholds;
  if (riskScore >= p90) return '#b91c1c';
  if (riskScore >= p66) return '#ea580c';
  if (riskScore >= p33) return '#ca8a04';
  return '#0f766e';
}

function getTextColor(riskScore: number, thresholds: [number, number, number]): string {
  if (riskScore === 0) return 'var(--muted)';
  const [p33] = thresholds;
  return riskScore >= p33 ? '#fff' : 'var(--text)';
}

function rowVal(row: HeatmapRow, col: string): number {
  return (row as unknown as Record<string, number>)[col] || 0;
}

const LEGEND_ITEMS = [
  { color: '#b91c1c', label: 'Highest risk (top 10%)' },
  { color: '#ea580c', label: 'High risk (66–90%)' },
  { color: '#ca8a04', label: 'Medium risk (33–66%)' },
  { color: '#0f766e', label: 'Lower risk (bottom 33%)' },
];

export default function RiskHeatmap({ matrix, totals }: RiskHeatmapProps): JSX.Element {
  const sortedMatrix = SEVERITY_ORDER.map(
    sev =>
      (matrix || []).find(r => r.severity === sev) || {
        severity: sev,
        sast: 0,
        dast: 0,
        sca: 0,
        iast: 0,
      }
  );

  // Compute risk scores (count × severity weight) for ALL cells to derive
  // percentile thresholds.  Zero-count cells are excluded so missing
  // technology data does not compress the active color range.
  const allRiskScores = sortedMatrix.flatMap(row =>
    TECH_COLS.map(t => rowVal(row, t) * (SEVERITY_WEIGHTS[row.severity] ?? 1))
  );
  const nonZeroSorted = [...allRiskScores].filter(v => v > 0).sort((a, b) => a - b);
  const p33 = percentile(nonZeroSorted, 33);
  const p66 = percentile(nonZeroSorted, 66);
  const p90 = percentile(nonZeroSorted, 90);
  const thresholds: [number, number, number] = [
    Math.max(p33, 1),
    Math.max(p66, p33 + 1),
    Math.max(p90, p66 + 1),
  ];

  return (
    <div style={{ overflowX: 'auto' }}>
      {/* Color legend */}
      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '0.5rem', alignItems: 'center' }}>
        {LEGEND_ITEMS.map(item => (
          <span key={item.color} style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.72rem', color: 'var(--text-muted, #94a3b8)' }}>
            <span style={{ display: 'inline-block', width: '12px', height: '12px', borderRadius: '2px', backgroundColor: item.color, flexShrink: 0 }} />
            {item.label}
          </span>
        ))}
      </div>
      <table className="heatmap-table">
        <thead>
          <tr>
            <th>Severity</th>
            {TECH_COLS.map(t => (
              <th key={t}>{t.toUpperCase()}</th>
            ))}
            <th>Total</th>
          </tr>
        </thead>
        <tbody>
          {sortedMatrix.map(row => {
            const weight = SEVERITY_WEIGHTS[row.severity] ?? 1;
            const rowTotal = TECH_COLS.reduce((sum, t) => sum + rowVal(row, t), 0);
            return (
              <tr key={row.severity}>
                <td
                  className={`heatmap-severity heatmap-severity--${row.severity.toLowerCase()}`}
                >
                  {row.severity}
                </td>
                {TECH_COLS.map(t => {
                  const val = rowVal(row, t);
                  const riskScore = val * weight;
                  return (
                    <td
                      key={t}
                      className="heatmap-cell"
                      style={{
                        backgroundColor: getHeatColor(riskScore, thresholds),
                        color: getTextColor(riskScore, thresholds),
                      }}
                    >
                      {val.toLocaleString()}
                    </td>
                  );
                })}
                <td className="heatmap-total">{rowTotal.toLocaleString()}</td>
              </tr>
            );
          })}
        </tbody>
        {totals && (
          <tfoot>
            <tr>
              <td>
                <strong>Total</strong>
              </td>
              {TECH_COLS.map(t => (
                <td key={t} className="heatmap-total">
                  {(totals[t] || 0).toLocaleString()}
                </td>
              ))}
              <td className="heatmap-total">
                <strong>
                  {TECH_COLS.reduce((s, t) => s + (totals[t] || 0), 0).toLocaleString()}
                </strong>
              </td>
            </tr>
          </tfoot>
        )}
      </table>
      {/* Methodology footnote */}
      <p style={{
        marginTop: '0.5rem',
        fontSize: '0.70rem',
        color: 'var(--text-muted, #94a3b8)',
        lineHeight: 1.4,
      }}>
        Cell numbers show raw issue counts. Cell color reflects{' '}
        <strong style={{ color: 'var(--text-muted, #94a3b8)' }}>risk-weighted score</strong>
        {' '}(count × severity weight — Critical ×4, High ×3, Medium ×2, Low ×1),
        ranked by percentile across all technology–severity combinations in this dataset.
      </p>
    </div>
  );
}


