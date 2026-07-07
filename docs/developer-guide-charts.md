# Developer Guide: Adding & Modifying Charts

## Architecture Overview

Charts flow through three layers:

```
AppScan on Cloud API (v4)
        ↓
Backend analytics route  (backend/app/api/v1/routes/analytics.py)
        ↓
Frontend API service     (frontend/src/shared/services/api.ts)
        ↓
Chart component          (frontend/src/shared/charts/*.tsx)
        ↓
App.tsx                  (renders chart with state data)
```

There is also a **widget registry** (`backend/app/plugins/widget_registry.py`) that defines which widget types can appear in saved dashboard configurations — separate from what is rendered directly in `App.tsx`.

---

## Part 1 — Modify an Existing Chart

### Change colours

Each chart component defines a `COLORS` constant at the top of the file. Edit the hex values directly.

**Example — `SeverityDonutChart.tsx`:**

```tsx
// frontend/src/shared/charts/SeverityDonutChart.tsx
const COLORS = {
  Critical: '#7f1d1d',   // was #b91c1c
  High: '#c2410c',       // was #ea580c
  Medium: '#a16207',     // was #ca8a04
  Low: '#065f46',        // was #0f766e
};
```

**Existing colour maps by chart:**

| File | Constant | Keys |
|---|---|---|
| `SeverityDonutChart.tsx` | `COLORS` | `Critical`, `High`, `Medium`, `Low` |
| `TechnologyBarChart.tsx` | `COLORS` | `SAST`, `DAST`, `SCA`, `IAST` |
| `StatusDistributionChart.tsx` | `COLORS` | `Open`, `Fixed`, `InProgress`, `Noise` |
| `RiskHeatmap.tsx` | `getHeatColor()` | Percentile-based (p33, p66, p90) |

### Add value labels to a bar chart

Add `<LabelList>` inside the `<Bar>` element:

```tsx
// frontend/src/shared/charts/TechnologyBarChart.tsx
import { ..., LabelList } from 'recharts';

<Bar dataKey="value" radius={[4, 4, 0, 0]}>
  {data.map((entry) => (
    <Cell key={entry.name} fill={COLORS[entry.name] || '#6b7280'} />
  ))}
  <LabelList dataKey="value" position="top" style={{ fontSize: 11 }} />
</Bar>
```

### Limit how many items a chart shows

Control this in `App.tsx` where the chart is rendered, not inside the component:

```tsx
// Show only top 5 apps
<TopAppsBarChart apps={(portfolioSummary?.top_apps_by_issues ?? []).slice(0, 5)} />
```

### Change chart height

Each chart accepts height via `<ResponsiveContainer height={...}>`. The default is `280`; change it in the component file:

```tsx
<ResponsiveContainer width="100%" height={360}>
```

---

## Part 2 — Add a New Chart Component

### Step 1 — Create the component

File: `frontend/src/shared/charts/MyNewChart.tsx`

```tsx
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
} from 'recharts';

interface MyNewChartProps {
  data: { month: string; count: number }[];
}

export default function MyNewChart({ data }: MyNewChartProps) {
  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={data} margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
        <XAxis dataKey="month" tick={{ fontSize: 11 }} />
        <YAxis />
        <Tooltip formatter={(v: number) => v.toLocaleString()} />
        <Line
          type="monotone"
          dataKey="count"
          stroke="#6366f1"
          strokeWidth={2}
          dot={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
```

All charts use [Recharts](https://recharts.org). Available chart types: `LineChart`, `BarChart`, `PieChart`, `AreaChart`, `RadarChart`, `ScatterChart`.

### Step 2 — Export from the barrel

File: `frontend/src/shared/charts/index.ts`

```ts
export { default as MyNewChart } from './MyNewChart';
// ... existing exports
```

### Step 3 — Add the backend analytics endpoint

File: `backend/app/api/v1/routes/analytics.py`

Add a route function following the existing pattern. All routes call `build_read_service(user)` to get a scoped service, then aggregate the data:

```python
@router.get("/my-new-metric")
async def my_new_metric(
    user: Annotated[UserContext, Depends(get_current_user)],
    asset_group_ids: list[str] = Query(default=[]),
) -> list[dict]:
    svc = build_read_service(user)
    raw = await svc.get_issues(asset_group_ids=asset_group_ids)
    # Aggregate raw data into your required shape, e.g.:
    result = aggregate_by_month(raw)
    return result
```

Register the route in the router if your endpoint is in a new file (existing analytics routes are already wired in `router.py`).

### Step 4 — Add the API call in the frontend service

File: `frontend/src/shared/services/api.ts`

```ts
export async function getMyNewMetric(
  params?: Record<string, string>
): Promise<{ month: string; count: number }[]> {
  const { data } = await api.get('/analytics/my-new-metric', { params });
  return data;
}
```

### Step 5 — Wire state and fetch in `App.tsx`

```tsx
// 1. Add state near the other useState declarations (~line 162)
const [myData, setMyData] = useState<{ month: string; count: number }[]>([]);

// 2. Fetch — add inside the existing loadAnalytics() / useEffect block
const myResult = await getMyNewMetric(buildAnalyticsParams());
setMyData(myResult);

// 3. Import the component
import { MyNewChart } from '../shared/charts';

// 4. Render in JSX
<MyNewChart data={myData} />
```

---

## Part 3 — Register a New Widget Type (for saved dashboards)

If the chart should be selectable when a user builds a **saved dashboard** (not just a static panel), register it in the backend widget registry.

File: `backend/app/plugins/widget_registry.py`

```python
{
    "type": "my_new_chart",           # unique key — matched in frontend switch/case
    "title": "My New Chart",
    "category": "trend",              # kpi | trend | mttr | risk | pipeline
    "description": "One-line description shown in the widget picker.",
    "default_config": {
        "time_range": "6m",
        "group_by": "month",
    },
    "allowed_roles": [
        "PlatformAdmin", "SecurityManager", "AppOwner", "Developer", "Auditor"
    ],
},
```

The `GET /api/v1/dashboards/widget-registry` endpoint returns this list. The frontend uses it to populate the widget picker. When the dashboard renders a saved widget it switches on `widget.type` to decide which chart component to render — add a matching case in the dashboard render logic in `App.tsx`.

---

## Part 4 — View Modes

`App.tsx` supports three view modes (`general`, `large`, `soc`) stored in `localStorage` under key `aspm_dashboard_view_mode`. Gate chart visibility or sizing by mode:

```tsx
// Show different charts depending on mode
{viewMode === 'soc' && <MyNewChart data={myData} />}
{viewMode !== 'soc' && <SeverityDonutChart {...stats} />}

// Or pass different height props
<MyNewChart data={myData} height={viewMode === 'large' ? 400 : 280} />
```

---

## Existing Chart Components

| Component | Chart type | Data source endpoint | Props |
|---|---|---|---|
| `SeverityDonutChart` | Donut/Pie | `/analytics/statistics` | `critical`, `high`, `medium`, `low` |
| `TechnologyBarChart` | Vertical bar | `/analytics/statistics` | `sast`, `dast`, `sca`, `iast` |
| `StatusDistributionChart` | Pie | `/analytics/statistics` | `statuses: [{status, count}]` |
| `RiskHeatmap` | CSS grid heatmap | `/analytics/statistics` | `matrix: [{severity, sast, dast, sca, iast}]` |
| `TopAppsBarChart` | Horizontal stacked bar | `/analytics/portfolio-summary` | `apps: [{app_id, app_name, critical, high, ...}]` |
| `DataCompletenessIndicator` | Progress bars | `/analytics/statistics` | completeness metadata fields |

---

## Quick Reference

| Goal | File to edit |
|---|---|
| Change chart colours / layout / labels | `frontend/src/shared/charts/<ChartName>.tsx` |
| Change what data a chart receives | `App.tsx` (state + fetch call) |
| Add a new analytics endpoint | `backend/app/api/v1/routes/analytics.py` |
| Add a new frontend API function | `frontend/src/shared/services/api.ts` |
| Register chart as a saveable widget | `backend/app/plugins/widget_registry.py` |
| Chart library docs | https://recharts.org |
