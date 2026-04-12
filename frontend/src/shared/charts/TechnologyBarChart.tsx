import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';

interface TechnologyBarProps {
  sast: number;
  dast: number;
  sca: number;
  iast: number;
}

const COLORS: Record<string, string> = {
  SAST: '#6366f1',
  DAST: '#ec4899',
  SCA: '#14b8a6',
  IAST: '#f59e0b',
};

export default function TechnologyBarChart({ sast, dast, sca, iast }: TechnologyBarProps) {
  const data = [
    { name: 'SAST', value: sast },
    { name: 'DAST', value: dast },
    { name: 'SCA', value: sca },
    { name: 'IAST', value: iast },
  ];

  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={data} margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
        <XAxis dataKey="name" tick={{ fontSize: 12 }} />
        <YAxis
          tickFormatter={(v: number) => (v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v))}
        />
        <Tooltip formatter={(value: number) => value.toLocaleString()} />
        <Bar dataKey="value" radius={[4, 4, 0, 0]}>
          {data.map((entry) => (
            <Cell key={entry.name} fill={COLORS[entry.name] || '#6b7280'} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
