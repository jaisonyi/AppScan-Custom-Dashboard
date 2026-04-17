import axios from 'axios';

function resolveApiBaseUrl(): string {
  if (typeof window === 'undefined') {
    return 'http://localhost:8000/api/v1';
  }
  const protocol = window.location.protocol || 'http:';
  const host = window.location.hostname || 'localhost';
  return `${protocol}//${host}:8000/api/v1`;
}

const api = axios.create({
  baseURL: resolveApiBaseUrl(),
  timeout: 15000,
});

const TOKEN_KEY = 'aspm_access_token';
const EXTERNAL_TOKEN_KEY = 'aspm_external_bearer_token';

type LoginPayload = {
  username: string;
  role: string;
  asset_group_ids: string[];
};

function getToken(): string | null {
  return window.sessionStorage.getItem(TOKEN_KEY) || window.localStorage.getItem(EXTERNAL_TOKEN_KEY);
}

function setToken(token: string): void {
  window.sessionStorage.setItem(TOKEN_KEY, token);
}

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export async function login(payload: LoginPayload): Promise<void> {
  const { data } = await api.post('/auth/login', payload);
  if (data?.access_token) {
    setToken(data.access_token);
  }
}

export async function getAuthMode(): Promise<{
  auth_mode: string;
  oidc_configured: boolean;
  oidc_missing_fields: string[];
}> {
  const { data } = await api.get('/auth/mode');
  return data;
}

export async function getCurrentUser(): Promise<{
  source?: string;
  subject?: string;
  display_name?: string;
  first_name?: string;
  last_name?: string;
  username?: string;
  email?: string;
  role?: string;
  role_id?: string;
  asoc_user_id?: string;
  organization_name?: string;
  tenant_name?: string;
  tenant_id?: string;
  tenant_region?: string;
  asset_group_ids?: string[];
}> {
  const { data } = await api.get('/auth/current-user');
  return data;
}

export function setExternalBearerToken(token: string): void {
  if (!token.trim()) {
    window.localStorage.removeItem(EXTERNAL_TOKEN_KEY);
    return;
  }
  window.localStorage.setItem(EXTERNAL_TOKEN_KEY, token.trim());
}

export async function getList(path: string): Promise<any[]> {
  const { data } = await api.get(path);
  return data;
}

export async function getObject(path: string): Promise<any> {
  const { data } = await api.get(path);
  return data;
}

export async function postObject(path: string, payload: any): Promise<any> {
  const { data } = await api.post(path, payload);
  return data;
}

export async function putObject(path: string, payload: any): Promise<any> {
  const { data } = await api.put(path, payload);
  return data;
}

export async function deleteObject(path: string): Promise<any> {
  const { data } = await api.delete(path);
  return data;
}

export async function downloadReportArtifact(reportId: string, fallbackFileName?: string): Promise<void> {
  const response = await api.get(`/reports/history/${reportId}/download`, {
    responseType: 'blob',
  });
  const blob = new Blob([response.data], {
    type: response.headers['content-type'] || 'application/octet-stream',
  });
  const contentDisposition = response.headers['content-disposition'] as string | undefined;
  const nameFromHeader = contentDisposition?.match(/filename="?([^";]+)"?/)?.[1];
  const fileName = nameFromHeader || fallbackFileName || `${reportId}.json`;
  const url = window.URL.createObjectURL(blob);
  const anchor = window.document.createElement('a');
  anchor.href = url;
  anchor.download = fileName;
  window.document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}

/* ── New analytics endpoints (Phase 3) ── */

export async function getIssueCounts(params?: Record<string, string>): Promise<any> {
  const { data } = await api.get('/analytics/issue-counts', { params });
  return data;
}

export async function getChartData(params?: Record<string, string>): Promise<any> {
  const { data } = await api.get('/analytics/chart-data', { params });
  return data;
}

export async function getRiskHeatmap(params?: Record<string, string>): Promise<any> {
  const { data } = await api.get('/analytics/risk-heatmap', { params });
  return data;
}

export async function getTopApps(params?: Record<string, string>): Promise<any> {
  const { data } = await api.get('/analytics/top-apps', { params });
  return data;
}

export async function getStatusDistribution(params?: Record<string, string>): Promise<any> {
  const { data } = await api.get('/analytics/status-distribution', { params });
  return data;
}

export async function getTechnologyBreakdown(params?: Record<string, string>): Promise<any> {
  const { data } = await api.get('/analytics/technology-breakdown', { params });
  return data;
}

export async function getSeverityTrend(params?: Record<string, string>): Promise<any> {
  const { data } = await api.get('/analytics/severity-trend', { params });
  return data;
}

/* ── Endpoint / Data Source management ── */

export type EndpointInfo = {
  id: string;
  url: string;
  label: string;
};

export type ManagedEndpointInfo = {
  id: string;
  url: string;
  label: string;
  api_key: string;
  has_secret: boolean;
  verify_ssl: boolean;
  enabled: boolean;
};

export type EndpointStatusResult = {
  id: string;
  url: string;
  label: string;
  ok: boolean;
  latency_ms: number | null;
  error: string | null;
};

export type DataSourceIdentity = {
  id: string;
  label: string;
  url: string;
  tenant_name: string | null;
  api_user_name: string | null;
  api_user_role: string | null;
  api_user_email: string | null;
  last_probed_at: string | null;
  last_probe_ok: boolean | null;
};

export async function getEndpoints(): Promise<{ endpoints: EndpointInfo[]; total: number }> {
  const { data } = await api.get('/endpoints');
  return data;
}

export async function getManagedEndpoints(): Promise<{ endpoints: ManagedEndpointInfo[]; total: number }> {
  const { data } = await api.get('/endpoints/manage');
  return data;
}

export async function getEndpointStatus(): Promise<{ results: EndpointStatusResult[]; total: number }> {
  const { data } = await api.get('/endpoints/status');
  return data;
}

export async function getDataSourceIdentities(opts?: { autoRefreshStale?: boolean }): Promise<{ identities: DataSourceIdentity[]; total: number }> {
  const params: Record<string, string> = {};
  if (opts?.autoRefreshStale) params.auto_refresh_stale = 'true';
  const { data } = await api.get('/endpoints/identities', { params });
  return data;
}

export async function refreshDataSourceIdentities(): Promise<{ identities: DataSourceIdentity[]; total: number }> {
  const { data } = await api.post('/endpoints/refresh-identities');
  return data;
}

export async function createEndpoint(payload: { url: string; label: string; api_key: string; api_secret: string; verify_ssl?: boolean }): Promise<{ endpoints: ManagedEndpointInfo[]; total: number }> {
  const { data } = await api.post('/endpoints', payload);
  return data;
}

export async function updateEndpoint(dsId: string, payload: { url?: string; label?: string; api_key?: string; api_secret?: string; verify_ssl?: boolean; enabled?: boolean }): Promise<{ endpoints: ManagedEndpointInfo[]; total: number }> {
  const { data } = await api.put(`/endpoints/${dsId}`, payload);
  return data;
}

export async function deleteEndpoint(dsId: string): Promise<{ endpoints: ManagedEndpointInfo[]; total: number }> {
  const { data } = await api.delete(`/endpoints/${dsId}`);
  return data;
}

export type WorkerStatus = {
  running: boolean;
  last_success_at: string | null;
  last_error_at: string | null;
  last_error: string | null;
  run_count: number;
  error_count: number;
  next_run_at: string | null;
  interval_seconds: number | null;
  cache_populated: boolean;
  cache_expires_at: string | null;
};

export async function getWorkerStatus(): Promise<WorkerStatus> {
  const { data } = await api.get('/analytics/worker-status');
  return data;
}
