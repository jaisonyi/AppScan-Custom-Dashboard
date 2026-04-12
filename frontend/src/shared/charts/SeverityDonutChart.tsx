import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';

interface SeverityDonutProps {
  critical: number;
  high: number;
  medium: number;
  low: number;
}

const COLORS = {
  Critical: '#b91c1c',
  High: '#ea580c',
  Medium: '#ca8a04',
  Low: '#0f766e',
};

export default function SeverityDonutChart({ critical, high, medium, low }: SeverityDonutProps) {
  const data = [
    { name: 'Critical', value: critical },
    { name: 'High', value: high },
    { name: 'Medium', value: medium },
    { name: 'Low', value: low },
  ].filter(d => d.value > 0);

  const total = critical + high + medium + low;

  return (
    <ResponsiveContainer width="100%" height={280}>
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius={60}
          outerRadius={100}
          paddingAngle={2}
          dataKey="value"
          label={({ name, percent }: { name: string; percent: number }) =>
            `${name} ${(percent * 100).toFixed(1)}%`
          }
        >
          {data.map((entry) => (
            <Cell key={entry.name} fill={COLORS[entry.name as keyof typeof COLORS]} />
          ))}
        </Pie>
        <Tooltip formatter={(value: number) => value.toLocaleString()} />
        <Legend />
        <text x="50%" y="50%" textAnchor="middle">
          <tspan
            x="50%"
            dy="-0.3em"
            style={{ fontSize: '1.2rem', fontWeight: 600 }}
          >
            {total.toLocaleString()}
          </tspan>
          <tspan
            x="50%"
            dy="1.4em"
            style={{ fontSize: '0.65rem', fill: '#888' }}
          >
            Critical–Low only
          </tspan>
        </text>
      </PieChart>
    </ResponsiveContainer>
  );
}
