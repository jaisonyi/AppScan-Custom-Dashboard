import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';

interface StatusItem {
  status: string;
  count: number;
}

interface StatusDistributionProps {
  statuses: StatusItem[];
}

const COLORS: Record<string, string> = {
  Open: '#ef4444',
  Fixed: '#22c55e',
  InProgress: '#3b82f6',
  Noise: '#9ca3af',
};

/**
 * Minimum slice percentage to show an inline label.
 * Slices smaller than this threshold are too narrow to label without
 * overlapping adjacent labels.  Their data is instead shown in the
 * rich legend below the chart.
 */
const LABEL_THRESHOLD = 0.04; // 4 %

const RADIAN = Math.PI / 180;

interface LabelProps {
  cx: number;
  cy: number;
  midAngle: number;
  outerRadius: number;
  percent: number;
  name: string;
}

/** Render an inline label only for slices large enough to avoid collision. */
function renderCustomLabel({ cx, cy, midAngle, outerRadius, percent, name }: LabelProps) {
  if (percent < LABEL_THRESHOLD) return null;
  const radius = outerRadius + 22;
  const x = cx + radius * Math.cos(-midAngle * RADIAN);
  const y = cy + radius * Math.sin(-midAngle * RADIAN);
  return (
    <text
      x={x}
      y={y}
      fill="var(--text, #e2e8f0)"
      textAnchor={x > cx ? 'start' : 'end'}
      dominantBaseline="central"
      fontSize={11}
    >
      {`${name} ${(percent * 100).toFixed(1)}%`}
    </text>
  );
}

interface LegendPayloadEntry {
  value: string;
  color: string;
}

export default function StatusDistributionChart({ statuses }: StatusDistributionProps) {
  const data = (statuses || [])
    .map(s => ({ name: s.status, value: s.count }))
    .filter(d => d.value > 0);

  const total = data.reduce((sum, d) => sum + d.value, 0);

  /** Custom legend showing count + percentage for every entry. */
  function renderLegend({ payload }: { payload?: LegendPayloadEntry[] }) {
    return (
      <ul style={{
        listStyle: 'none', padding: 0, margin: '6px 0 0',
        display: 'flex', flexWrap: 'wrap', justifyContent: 'center',
        gap: '4px 16px',
      }}>
        {(payload || []).map((entry) => {
          const item = data.find(d => d.name === entry.value);
          const count = item?.value ?? 0;
          const pct = total > 0 ? (count / total * 100).toFixed(1) : '0.0';
          const isSmall = total > 0 && count / total < LABEL_THRESHOLD;
          return (
            <li key={entry.value} style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.73rem' }}>
              <span style={{
                width: 10, height: 10, borderRadius: 2,
                backgroundColor: entry.color, flexShrink: 0,
                display: 'inline-block',
              }} />
              <span style={{ color: 'var(--text, #e2e8f0)' }}>{entry.value}</span>
              <span style={{
                color: isSmall ? 'var(--text, #e2e8f0)' : 'var(--muted, #94a3b8)',
                fontWeight: isSmall ? 600 : 400,
              }}>
                {count.toLocaleString()} ({pct}%)
              </span>
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={280}>
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="42%"
          outerRadius={85}
          paddingAngle={2}
          dataKey="value"
          labelLine={false}
          label={renderCustomLabel as any}
        >
          {data.map((entry) => (
            <Cell key={entry.name} fill={COLORS[entry.name] || '#6b7280'} />
          ))}
        </Pie>
        <Tooltip formatter={(value: number) => value.toLocaleString()} />
        <Legend content={renderLegend as any} />
      </PieChart>
    </ResponsiveContainer>
  );
}
