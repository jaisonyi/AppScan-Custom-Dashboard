import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';

interface AppIssue {
  app_id: string;
  app_name: string;
  total: number;
  critical: number;
  high: number;
  medium?: number;
  low?: number;
}

interface TopAppsBarProps {
  apps: AppIssue[];
}

export default function TopAppsBarChart({ apps }: TopAppsBarProps) {
  const data = (apps || [])
    .map(a => ({
      name: a.app_name?.length > 20 ? a.app_name.slice(0, 18) + '…' : a.app_name,
      fullName: a.app_name,
      Critical: a.critical || 0,
      High: a.high || 0,
      Medium: a.medium || 0,
      Low: a.low || 0,
    }))
    .sort((a, b) =>
      (b.Critical + b.High + b.Medium + b.Low) - (a.Critical + a.High + a.Medium + a.Low)
    );

  return (
    <ResponsiveContainer width="100%" height={Math.max(300, data.length * 32)}>
      <BarChart data={data} layout="vertical" margin={{ top: 5, right: 20, left: 120, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
        <XAxis
          type="number"
          tickFormatter={(v: number) => (v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v))}
        />
        <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={110} />
        <Tooltip
          formatter={(value: number) => value.toLocaleString()}
          labelFormatter={(label: string) => {
            const item = data.find(d => d.name === label);
            return item?.fullName || label;
          }}
        />
        <Legend />
        <Bar dataKey="Critical" stackId="a" fill="#b91c1c" />
        <Bar dataKey="High" stackId="a" fill="#ea580c" />
        <Bar dataKey="Medium" stackId="a" fill="#ca8a04" />
        <Bar dataKey="Low" stackId="a" fill="#0f766e" />
      </BarChart>
    </ResponsiveContainer>
  );
}
