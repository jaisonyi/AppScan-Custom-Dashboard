import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  getCurrentUser,
  getAuthMode,
  getList,
  getObject,
  login,
  setExternalBearerToken,
  getEndpoints,
  getEndpointStatus,
  getManagedEndpoints,
  createEndpoint,
  updateEndpoint,
  deleteEndpoint,
  type EndpointInfo,
  type ManagedEndpointInfo,
  type EndpointStatusResult,
} from '../shared/services/api';
import {
  SeverityDonutChart,
  TechnologyBarChart,
  StatusDistributionChart,
  RiskHeatmap,
  TopAppsBarChart,
  DataCompletenessIndicator,
} from '../shared/charts';
import { getChartData, getIssueCounts } from '../shared/services/api';

const STATUS_COLORS: Record<string, string> = {
  completed: '#0b8f6a',
  running: '#1d4ed8',
  failed: '#be123c',
  unknown: '#64748b',
};

type ViewMode = 'general' | 'large' | 'soc';
type CenterChartMode = 'prioritization' | 'findings' | 'scans';
type FindingsPeriod = 'week' | 'month' | 'year';
type ScanPeriod = 'day' | 'week' | 'month';
type ScanTimeBucketPeriod = 'week' | 'month' | 'year';
type ScanSeveritySource = 'derived' | 'native' | 'hybrid';
type ComplianceRule = 'critical_high' | 'any_open' | 'custom';
type ComplianceThreshold = 'critical' | 'high' | 'medium' | 'low';
type ReportWindow = 'all' | '7d' | '30d' | '90d' | '365d';
type ScopeFilters = {
  assetGroupIds: string[];
  applicationIds: string[];
  issueTechnologies: string[];
  vulnerabilities: string[];
  scanTypes: string[];
  scanStatuses: string[];
  reportWindow: ReportWindow;
};
type ScopePanel = 'applications' | 'assetGroups' | 'issues' | 'scans' | 'reports' | 'endpoints' | null;
type FreshnessInfo = {
  source?: string;
  generated_at?: string | null;
  cached_at?: string | null;
  expires_at?: string | null;
};

type FreshnessDomain = 'statistics' | 'portfolio';

type IssueFilterOptions = {
  technologies: Array<{ value: string; label?: string; count?: number }>;
  vulnerabilities: Array<{ value: string; label?: string; count?: number }>;
  unclassified_count?: number;
};

type CurrentUserProfile = {
  source?: string;
  subject?: string;
  display_name?: string;
  first_name?: string;
  last_name?: string;
  username?: string;
  email?: string;
  role?: string;
  organization_name?: string;
  tenant_name?: string;
  tenant_id?: string;
  tenant_region?: string;
};

const VIEW_MODE_STORAGE_KEY = 'aspm_dashboard_view_mode';
const SCOPE_FILTERS_STORAGE_KEY = 'aspm_scope_filters_enabled';
const DEFAULT_SCOPE_FILTERS_ENABLED =
  String(import.meta.env.VITE_SCOPE_FILTERS_ENABLED ?? 'true').toLowerCase() !== 'false';

const VIEW_MODE_OPTIONS: Array<{ key: ViewMode; label: string }> = [
  { key: 'general', label: 'General' },
  { key: 'large', label: 'Larger Chart' },
  { key: 'soc', label: 'SOC Style' },
];

function getStoredViewMode(): ViewMode {
  if (typeof window === 'undefined') {
    return 'general';
  }
  try {
    const value = window.localStorage.getItem(VIEW_MODE_STORAGE_KEY);
    if (value === 'general' || value === 'large' || value === 'soc') {
      return value;
    }
  } catch (error) {
    console.warn('Unable to read stored dashboard view mode', error);
  }
  return 'general';
}

function getStoredScopeFiltersEnabled(): boolean {
  if (typeof window === 'undefined') {
    return DEFAULT_SCOPE_FILTERS_ENABLED;
  }
  try {
    const value = window.localStorage.getItem(SCOPE_FILTERS_STORAGE_KEY);
    if (value === '1') {
      return true;
    }
    if (value === '0') {
      return false;
    }
  } catch (error) {
    console.warn('Unable to read stored scope-filter mode', error);
  }
  return DEFAULT_SCOPE_FILTERS_ENABLED;
}

function formatFreshnessTime(info?: FreshnessInfo): string {
  const iso = info?.generated_at || info?.cached_at;
  if (!iso) {
    return 'n/a';
  }
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return 'n/a';
  }
  return parsed.toLocaleTimeString();
}

export function App() {
  const [scans, setScans] = useState<any[]>([]);
  const [applications, setApplications] = useState<any[]>([]);
  const [assetGroups, setAssetGroups] = useState<any[]>([]);
  const [issues, setIssues] = useState<any[]>([]);
  const [stats, setStats] = useState<any>({});
  const [portfolioSummary, setPortfolioSummary] = useState<any>({});
  const [prioritization, setPrioritization] = useState<any>({});
  const [findingsSeries, setFindingsSeries] = useState<any[]>([]);
  const [scanSeries, setScanSeries] = useState<any[]>([]);
  const [workbenchTrends, setWorkbenchTrends] = useState<any>({});
  const [centerChartMode, setCenterChartMode] = useState<CenterChartMode>('prioritization');
  const [findingsPeriod, setFindingsPeriod] = useState<FindingsPeriod>('month');
  const [scanPeriod, setScanPeriod] = useState<ScanPeriod>('month');
  const [scanSeveritySource, setScanSeveritySource] = useState<ScanSeveritySource>('hybrid');
  const [scanTimeBucketPeriod, setScanTimeBucketPeriod] = useState<ScanTimeBucketPeriod>('month');
  const [scanTimeBucketKey, setScanTimeBucketKey] = useState<string>('lt5');
  const [scanTimeTechFilter, setScanTimeTechFilter] = useState<'total' | 'sast' | 'sca' | 'dast'>('total');
  const [fileSizeBucketPeriod, setFileSizeBucketPeriod] = useState<ScanTimeBucketPeriod>('month');
  const [fileSizeBucketKey, setFileSizeBucketKey] = useState<string>('lt1');
  const [fileSizeTechFilter, setFileSizeTechFilter] = useState<'total' | 'sast' | 'sca'>('total');
  const [dastCoverageBucketPeriod, setDastCoverageBucketPeriod] = useState<ScanTimeBucketPeriod>('month');
  const [dastCoverageBucketKey, setDastCoverageBucketKey] = useState<string>('lt10');
  const [complianceRule, setComplianceRule] = useState<ComplianceRule>('critical_high');
  const [complianceThreshold, setComplianceThreshold] = useState<ComplianceThreshold>('high');
  const [trend, setTrend] = useState<any[]>([]);
  const [pipelineBom, setPipelineBom] = useState<any[]>([]);
  const [externalToken, setExternalToken] = useState('');
  const [authMode, setAuthMode] = useState('local');
  const [viewMode, setViewMode] = useState<ViewMode>(() => getStoredViewMode());
  const [scopeFiltersEnabled, setScopeFiltersEnabled] = useState<boolean>(() => getStoredScopeFiltersEnabled());
  const [scopePanel, setScopePanel] = useState<ScopePanel>(null);
  const [applicationSearch, setApplicationSearch] = useState('');
  const [assetGroupSearch, setAssetGroupSearch] = useState('');
  const [vulnerabilitySearch, setVulnerabilitySearch] = useState('');
  const [issueFilterOptions, setIssueFilterOptions] = useState<IssueFilterOptions>({
    technologies: [],
    vulnerabilities: [],
    unclassified_count: 0,
  });
  const [currentUser, setCurrentUser] = useState<CurrentUserProfile | null>(null);
  const [appliedScopeFilters, setAppliedScopeFilters] = useState<ScopeFilters>({
    assetGroupIds: [],
    applicationIds: [],
    issueTechnologies: [],
    vulnerabilities: [],
    scanTypes: [],
    scanStatuses: [],
    reportWindow: 'all',
  });
  const [pendingScopeFilters, setPendingScopeFilters] = useState<ScopeFilters>({
    assetGroupIds: [],
    applicationIds: [],
    issueTechnologies: [],
    vulnerabilities: [],
    scanTypes: [],
    scanStatuses: [],
    reportWindow: 'all',
  });
  const [isRefreshingLive, setIsRefreshingLive] = useState(false);
  const [endpoints, setEndpoints] = useState<EndpointInfo[]>([]);
  const [endpointStatus, setEndpointStatus] = useState<EndpointStatusResult[] | null>(null);
  const [endpointStatusLoading, setEndpointStatusLoading] = useState(false);
  // Endpoint management modal state
  const [managedEndpoints, setManagedEndpoints] = useState<ManagedEndpointInfo[]>([]);
  const [epModalOpen, setEpModalOpen] = useState(false);
  const [epModalLoading, setEpModalLoading] = useState(false);
  const [epModalError, setEpModalError] = useState('');
  const [epEditIdx, setEpEditIdx] = useState<number | null>(null);  // null = adding new
  const [epForm, setEpForm] = useState({ url: '', label: '', api_key: '', api_secret: '' });
  const [freshness, setFreshness] = useState<Record<FreshnessDomain, FreshnessInfo>>({
    statistics: {},
    portfolio: {},
  });
  const [error, setError] = useState('');
  const [chartData, setChartData] = useState<any>(null);
  const [issueCounts, setIssueCounts] = useState<any>(null);
  const [chartDataLoading, setChartDataLoading] = useState(false);

  function normalizeIdList(values: string[]): string[] {
    const seen = new Set<string>();
    const out: string[] = [];
    values.forEach((raw) => {
      const value = String(raw || '').trim();
      if (!value || seen.has(value)) {
        return;
      }
      seen.add(value);
      out.push(value);
    });
    return out;
  }

  function normalizeStringList(values: string[]): string[] {
    const seen = new Set<string>();
    const out: string[] = [];
    values.forEach((raw) => {
      const value = String(raw || '').trim();
      if (!value || seen.has(value)) {
        return;
      }
      seen.add(value);
      out.push(value);
    });
    return out;
  }

  function resolveReportWindowRange(window: ReportWindow): { fromDate?: string; toDate?: string } {
    if (window === 'all') {
      return {};
    }
    const now = new Date();
    const start = new Date(now);
    const days = window === '7d' ? 7 : window === '30d' ? 30 : window === '90d' ? 90 : 365;
    start.setUTCDate(start.getUTCDate() - days);
    return {
      fromDate: start.toISOString(),
      toDate: now.toISOString(),
    };
  }

  function buildAnalyticsPath(path: string, options?: { refresh?: boolean; filters?: ScopeFilters; extra?: Record<string, string> }): string {
    const params = new URLSearchParams();
    const selectedFilters = options?.filters || appliedScopeFilters;
    if (scopeFiltersEnabled) {
      const allAssetIds = normalizeIdList(assetGroups.map((item) => String(item?.id || '')));
      const selectedAssetIds = normalizeIdList(selectedFilters.assetGroupIds);
      const hasScopedAssetGroupFilter =
        selectedAssetIds.length > 0 &&
        allAssetIds.length > 0 &&
        selectedAssetIds.length < allAssetIds.length;

      if (hasScopedAssetGroupFilter) {
        selectedAssetIds.forEach((id) => params.append('asset_group_ids', id));
      }

      normalizeIdList(selectedFilters.applicationIds).forEach((id) => params.append('application_ids', id));
      normalizeStringList(selectedFilters.issueTechnologies).forEach((item) =>
        params.append('issue_technologies', item),
      );
      normalizeStringList(selectedFilters.vulnerabilities).forEach((item) =>
        params.append('vulnerabilities', item),
      );
      normalizeStringList(selectedFilters.scanTypes).forEach((item) =>
        params.append('scan_types', item),
      );
      normalizeStringList(selectedFilters.scanStatuses).forEach((item) =>
        params.append('scan_statuses', item),
      );

      const reportRange = resolveReportWindowRange(selectedFilters.reportWindow || 'all');
      if (reportRange.fromDate) {
        params.set('from_date', reportRange.fromDate);
      }
      if (reportRange.toDate) {
        params.set('to_date', reportRange.toDate);
      }
    }
    if (options?.refresh) {
      params.set('refresh', 'true');
    }
    if (options?.extra) {
      Object.entries(options.extra).forEach(([key, value]) => params.set(key, value));
    }
    const query = params.toString();
    return query ? `${path}?${query}` : path;
  }

  function hasMeaningfulStats(payload: any): boolean {
    if (!payload || typeof payload !== 'object') {
      return false;
    }
    return (
      toNumber(payload?.total_issues) > 0
      || toNumber(payload?.active_issues) > 0
      || toNumber(payload?.scan_count) > 0
      || toNumber(payload?.application_count) > 0
      || toNumber(payload?.asset_group_count) > 0
    );
  }

  function deriveStatsFromPortfolio(summary: any): any {
    const scanByStatus = (summary && typeof summary === 'object' ? summary.scan_count_by_status : {}) || {};
    const totalIssues = toNumber(summary?.total_issues);
    const activeIssues = toNumber(summary?.active_issues);
    const resolvedIssues = Math.max(totalIssues - activeIssues, 0);
    const openScans =
      toNumber(scanByStatus?.running)
      + toNumber(scanByStatus?.pending)
      + toNumber(scanByStatus?.queued)
      + toNumber(scanByStatus?.scheduled);

    return {
      total_issues: totalIssues,
      active_issues: activeIssues,
      resolved_issues: resolvedIssues,
      scan_count: toNumber(summary?.scan_count),
      application_count: toNumber(summary?.application_count),
      asset_group_count: toNumber(summary?.asset_group_count),
      failed_scans: toNumber(scanByStatus?.failed),
      open_scans: openScans,
      running_or_pending_scans: openScans,
      scan_count_by_status: scanByStatus,
      scan_count_by_type: summary?.scan_count_by_type || {},
    };
  }

  async function loadAnalytics(forceRefresh = false, filters?: ScopeFilters): Promise<void> {
    const safeGetObject = async (path: string, fallback: any): Promise<any> => {
      try {
        return await getObject(path);
      } catch (err) {
        console.error(err);
        return fallback;
      }
    };

    const effectiveFilters = filters || appliedScopeFilters;
    const bundlePath = buildAnalyticsPath('/analytics/bundle', {
      refresh: false,
      filters: effectiveFilters,
      extra: {
        findings_period: findingsPeriod,
        scan_period: scanPeriod,
        severity_source: scanSeveritySource,
        compliance_rule: complianceRule,
        compliance_threshold: complianceThreshold,
      },
    });

    const fallbackBundle = {
      statistics: stats || {},
      trend: trend || [],
      portfolio_summary: portfolioSummary || {},
      prioritization: prioritization || {},
      findings_series: { items: findingsSeries || [] },
      scan_series: { items: scanSeries || [] },
      workbench_trends: workbenchTrends || {},
      _freshness: freshness?.statistics || {},
    };

    const applyBundle = (bundlePayload: any) => {
      const nextPortfolio = bundlePayload?.portfolio_summary || {};
      const rawStats = bundlePayload?.statistics && typeof bundlePayload.statistics === 'object'
        ? { ...bundlePayload.statistics }
        : {};
      const previousStats = hasMeaningfulStats(stats) ? { ...stats } : {};
      const derivedStats = deriveStatsFromPortfolio(nextPortfolio || {});
      const statisticsPayload = hasMeaningfulStats(rawStats)
        ? rawStats
        : (hasMeaningfulStats(previousStats) ? { ...previousStats, ...rawStats } : { ...derivedStats, ...rawStats });

      const nextFreshness = bundlePayload?._freshness || {};
      setFreshness({
        statistics: nextFreshness,
        portfolio: nextFreshness,
      });
      setStats(statisticsPayload);
      setTrend(Array.isArray(bundlePayload?.trend) ? bundlePayload.trend : []);
      setPortfolioSummary(nextPortfolio);
      setPrioritization(bundlePayload?.prioritization || {});
      setFindingsSeries(Array.isArray(bundlePayload?.findings_series?.items) ? bundlePayload.findings_series.items : []);
      setScanSeries(Array.isArray(bundlePayload?.scan_series?.items) ? bundlePayload.scan_series.items : []);
      setWorkbenchTrends(bundlePayload?.workbench_trends || {});
    };

    const bundlePayload = await safeGetObject(bundlePath, fallbackBundle);
    applyBundle(bundlePayload);

    if (forceRefresh) {
      const refreshBundlePath = buildAnalyticsPath('/analytics/bundle', {
        refresh: true,
        filters: effectiveFilters,
        extra: {
          findings_period: findingsPeriod,
          scan_period: scanPeriod,
          severity_source: scanSeveritySource,
          compliance_rule: complianceRule,
          compliance_threshold: complianceThreshold,
        },
      });
      // Keep refresh non-blocking to avoid long empty/blocked states when tenant-wide
      // refresh requires heavy upstream reads.
      void safeGetObject(refreshBundlePath, bundlePayload || fallbackBundle).then((freshBundle) => {
        if (!freshBundle || typeof freshBundle !== 'object') {
          return;
        }
        applyBundle(freshBundle);
      });
    }
  }

  async function loadChartData(filters?: ScopeFilters): Promise<void> {
    setChartDataLoading(true);
    try {
      const chartPath = buildAnalyticsPath('/analytics/chart-data', { filters });
      const countPath = buildAnalyticsPath('/analytics/issue-counts', { filters });
      const [cd, ic] = await Promise.all([
        getObject(chartPath).catch(() => null),
        getObject(countPath).catch(() => null),
      ]);
      if (cd) setChartData(cd);
      if (ic) setIssueCounts(ic);
    } catch (err) {
      console.warn('Failed to load chart data:', err);
    } finally {
      setChartDataLoading(false);
    }
  }

  async function loadIssueFilterOptions(filters?: ScopeFilters, forceRefresh = false): Promise<void> {
    const path = buildAnalyticsPath('/analytics/filter-options', {
      refresh: forceRefresh,
      filters,
      extra: { vulnerability_limit: '2000' },
    });
    const response = await getObject(path);
    setIssueFilterOptions({
      technologies: Array.isArray(response?.technologies) ? response.technologies : [],
      vulnerabilities: Array.isArray(response?.vulnerabilities) ? response.vulnerabilities : [],
      unclassified_count: toNumber(response?.unclassified_count),
    });
  }

  async function refreshData(): Promise<void> {
    const [pb, applicationRows, assetGroupRows] = await Promise.all([
      getList('/pipeline-bom').catch((err) => {
        console.error(err);
        return [];
      }),
      getList('/applications').catch((err) => {
        console.error(err);
        return [];
      }),
      getList('/asset-groups').catch((err) => {
        console.error(err);
        return [];
      }),
    ]);

    setPipelineBom(Array.isArray(pb) ? pb : []);
    setApplications(Array.isArray(applicationRows) ? applicationRows : []);
    setAssetGroups(Array.isArray(assetGroupRows) ? assetGroupRows : []);

    let nextScopeFilters = appliedScopeFilters;
    if (scopeFiltersEnabled) {
      const allAssetGroupIds = normalizeIdList(assetGroupRows.map((row: any) => String(row?.id || '')));
      const safeAssetGroupIds =
        appliedScopeFilters.assetGroupIds.length > 0
          ? normalizeIdList(appliedScopeFilters.assetGroupIds.filter((id) => allAssetGroupIds.includes(id)))
          : allAssetGroupIds;

      const allowedApplications = applicationRows.filter((row: any) => {
        if (safeAssetGroupIds.length === 0) {
          return true;
        }
        return safeAssetGroupIds.includes(String(row?.asset_group_id || ''));
      });
      const allowedApplicationIds = normalizeIdList(allowedApplications.map((row: any) => String(row?.id || '')));
      const safeApplicationIds = normalizeIdList(
        appliedScopeFilters.applicationIds.filter((id) => allowedApplicationIds.includes(id)),
      );

      nextScopeFilters = {
        assetGroupIds: safeAssetGroupIds,
        applicationIds: safeApplicationIds,
        issueTechnologies: normalizeStringList(
          appliedScopeFilters.issueTechnologies.map((item) => String(item || '').toUpperCase()),
        ),
        vulnerabilities: normalizeStringList(appliedScopeFilters.vulnerabilities.map((item) => String(item || '').toLowerCase())),
        scanTypes: normalizeStringList(appliedScopeFilters.scanTypes.map((item) => String(item || '').toUpperCase())),
        scanStatuses: normalizeStringList(
          appliedScopeFilters.scanStatuses.map((item) => String(item || '').toLowerCase()),
        ),
        reportWindow: appliedScopeFilters.reportWindow || 'all',
      };
      setAppliedScopeFilters(nextScopeFilters);
      setPendingScopeFilters(nextScopeFilters);
    }

    await Promise.all([
      loadAnalytics(false, nextScopeFilters),
      loadChartData(nextScopeFilters),
    ]);
  }

  useEffect(() => {
    async function load() {
      try {
        const mode = await getAuthMode();
        setAuthMode(mode.auth_mode);

        if (mode.auth_mode === 'local') {
          await login({
            username: 'dashboard-user',
            role: 'SecurityManager',
            asset_group_ids: ['ag-1', 'ag-2'],
          });
        }

        await refreshData();
        // refreshData() now calls loadChartData(nextScopeFilters) internally
        try {
          const profile = await getCurrentUser();
          setCurrentUser(profile || null);
        } catch (profileError) {
          console.warn('Unable to load current user profile', profileError);
        }
        try {
          const epData = await getEndpoints();
          setEndpoints(epData.endpoints || []);
        } catch (epError) {
          console.warn('Unable to load endpoint list', epError);
        }
      } catch (err) {
        setError('Failed to authenticate or load dashboard data.');
        console.error(err);
      }
    }

    load();
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    try {
      window.localStorage.setItem(VIEW_MODE_STORAGE_KEY, viewMode);
    } catch (error) {
      console.warn('Unable to persist dashboard view mode', error);
    }
  }, [viewMode]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    try {
      window.localStorage.setItem(SCOPE_FILTERS_STORAGE_KEY, scopeFiltersEnabled ? '1' : '0');
    } catch (error) {
      console.warn('Unable to persist scope-filter mode', error);
    }
  }, [scopeFiltersEnabled]);

  useEffect(() => {
    if (!scopeFiltersEnabled || scopePanel !== 'issues') {
      return;
    }
    if (issueFilterOptions.technologies.length > 0 && issueFilterOptions.vulnerabilities.length > 0) {
      return;
    }
    loadIssueFilterOptions(appliedScopeFilters, false).catch((err) => {
      console.error(err);
    });
  }, [
    scopePanel,
    scopeFiltersEnabled,
    appliedScopeFilters,
    issueFilterOptions.technologies.length,
    issueFilterOptions.vulnerabilities.length,
  ]);

  useEffect(() => {
    async function syncBundleDrivenAnalytics() {
      try {
        await loadAnalytics(false, appliedScopeFilters);
      } catch (err) {
        console.error(err);
      }
    }
    syncBundleDrivenAnalytics();
  }, [findingsPeriod, scanPeriod, scanSeveritySource, complianceRule, complianceThreshold]);

  const summaryStatusCounts = portfolioSummary.scan_count_by_status || {};
  const statusBreakdown =
    Object.keys(summaryStatusCounts).length > 0
      ? Object.entries(summaryStatusCounts).reduce<Record<string, number>>((acc, [key, value]) => {
          acc[String(key).toLowerCase()] = toNumber(value);
          return acc;
        }, {})
      : scans.reduce<Record<string, number>>((acc, scan) => {
          const status = String(scan?.status || 'unknown').toLowerCase();
          acc[status] = (acc[status] || 0) + 1;
          return acc;
        }, {});

  const statusChartData = Object.keys(statusBreakdown).map((status) => ({
    status,
    count: statusBreakdown[status],
  }));

  function toNumber(value: unknown): number {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function compactLabel(value: unknown, maxLength = 20): string {
    const text = String(value ?? '');
    return text.length > maxLength ? `${text.slice(0, maxLength - 3)}...` : text;
  }

  function formatScanTimePeriodTick(value: unknown, period: ScanTimeBucketPeriod): string {
    const text = String(value ?? '');
    if (period === 'week') {
      const matched = text.match(/^(\d{4})-W(\d{2})$/);
      if (matched) {
        return `W${matched[2]}`;
      }
    }
    return text;
  }

  function formatScanTimePeriodLabel(value: unknown, period: ScanTimeBucketPeriod): string {
    const text = String(value ?? '');
    if (period === 'week') {
      const matched = text.match(/^(\d{4})-W(\d{2})$/);
      if (matched) {
        return `Week ${matched[2]}, ${matched[1]}`;
      }
    }
    if (period === 'month') {
      return text;
    }
    if (period === 'year') {
      return `Year ${text}`;
    }
    return text;
  }

  const totalIssues = toNumber(stats.total_issues ?? issues.length);
  const activeIssues = toNumber(stats.active_issues);
  const statusCounts = portfolioSummary.scan_count_by_status || {};

  const failedScans = toNumber(
    statusCounts.failed ?? scans.filter((scan) => String(scan?.status ?? '').toLowerCase().includes('fail')).length,
  );
  const fallbackRunningScans = scans.filter((scan) => {
    const status = String(scan?.status ?? '').toLowerCase();
    return status.includes('running') || status.includes('pending');
  }).length;
  const runningScans =
    statusCounts.running !== undefined || statusCounts.pending !== undefined
      ? toNumber(statusCounts.running) + toNumber(statusCounts.pending)
      : fallbackRunningScans;

  const scanTypeSource = portfolioSummary.scan_count_by_type || {};

  const scanTypeCounts = {
    DAST: toNumber(scanTypeSource.DAST),
    SAST: toNumber(scanTypeSource.SAST),
    SCA: toNumber(scanTypeSource.SCA),
    IAST: toNumber(scanTypeSource.IAST),
  };

  if (!scanTypeCounts.DAST && !scanTypeCounts.SAST && !scanTypeCounts.SCA && !scanTypeCounts.IAST) {
    const fallbackCounts = scans.reduce<Record<string, number>>(
      (acc, scan) => {
        const rawType = String(scan?.scan_type ?? scan?.type ?? scan?.technology ?? scan?.test_type ?? '').toUpperCase();
        if (rawType.includes('DAST')) {
          acc.DAST += 1;
        } else if (rawType.includes('SAST')) {
          acc.SAST += 1;
        } else if (rawType.includes('SCA')) {
          acc.SCA += 1;
        } else if (rawType.includes('IAST')) {
          acc.IAST += 1;
        }
        return acc;
      },
      { DAST: 0, SAST: 0, SCA: 0, IAST: 0 },
    );
    scanTypeCounts.DAST = fallbackCounts.DAST;
    scanTypeCounts.SAST = fallbackCounts.SAST;
    scanTypeCounts.SCA = fallbackCounts.SCA;
    scanTypeCounts.IAST = fallbackCounts.IAST;
  }

  const totalScans = toNumber(portfolioSummary.scan_count ?? scans.length);
  const applicationCount = toNumber(portfolioSummary.application_count ?? applications.length);
  const assetGroupCount = toNumber(portfolioSummary.asset_group_count ?? assetGroups.length);

  const severityBuckets = {
    critical: toNumber(stats.critical_issues),
    high: toNumber(stats.high_issues),
    medium: toNumber(stats.medium_issues),
    low: toNumber(stats.low_issues),
  };

  const resolvedIssues = Math.max(toNumber(stats.resolved_issues ?? totalIssues - activeIssues), 0);
  const highAndCritical = severityBuckets.critical + severityBuckets.high;
  const riskPressure = totalIssues > 0 ? Math.round((highAndCritical / totalIssues) * 100) : 0;
  const centerChartHeight = viewMode === 'large' ? 420 : viewMode === 'soc' ? 340 : 360;

  const severityChartData = [
    { severity: 'Critical', count: severityBuckets.critical, color: '#b91c1c' },
    { severity: 'High', count: severityBuckets.high, color: '#ea580c' },
    { severity: 'Medium', count: severityBuckets.medium, color: '#ca8a04' },
    { severity: 'Low', count: severityBuckets.low, color: '#0f766e' },
  ];

  const scanTypeChartData = [
    { type: 'DAST', count: scanTypeCounts.DAST },
    { type: 'SAST', count: scanTypeCounts.SAST },
    { type: 'SCA', count: scanTypeCounts.SCA },
    { type: 'IAST', count: scanTypeCounts.IAST },
  ];

  const topFailedApps: Array<[string, number]> = Array.isArray(portfolioSummary.failed_scans_by_application)
    ? portfolioSummary.failed_scans_by_application.slice(0, 10).map((row: any) =>
        [
          String(row.application_name || row.application_id || 'Unknown Application'),
          toNumber(row.count),
        ] as [string, number],
      )
    : Object.entries(
        scans.reduce<Record<string, number>>((acc, scan) => {
          const status = String(scan?.status ?? '').toLowerCase();
          if (!status.includes('fail')) {
            return acc;
          }
          const appName = String(
            scan?.application_name ?? scan?.app_name ?? scan?.application ?? scan?.application_id ?? 'Unknown Application',
          );
          acc[appName] = (acc[appName] || 0) + 1;
          return acc;
        }, {}),
      )
        .sort((a, b) => b[1] - a[1])
        .slice(0, 10);

  const prioritizationPayload = prioritization || {};
  const rawFindings = prioritizationPayload.raw_findings || {};
  const fixGroupTotals = prioritizationPayload.fix_groups?.totals || {};
  const mostCriticalFindings = Array.isArray(prioritizationPayload.most_critical)
    ? prioritizationPayload.most_critical
    : [];
  const correlatedFindings = Array.isArray(prioritizationPayload.correlated_findings)
    ? prioritizationPayload.correlated_findings
    : [];

  const mostCriticalHighTotal = mostCriticalFindings.reduce((sum: number, row: any) => sum + toNumber(row?.high), 0);
  const mostCriticalCriticalTotal = mostCriticalFindings.reduce((sum: number, row: any) => sum + toNumber(row?.critical), 0);
  const correlatedHighTotal = correlatedFindings.reduce((sum: number, row: any) => sum + toNumber(row?.high), 0);
  const correlatedCriticalTotal = correlatedFindings.reduce((sum: number, row: any) => sum + toNumber(row?.critical), 0);

  const prioritizationChartData = [
    {
      lane: 'Raw Findings',
      critical: toNumber(rawFindings.critical),
      high: toNumber(rawFindings.high),
      medium: toNumber(rawFindings.medium),
      low: toNumber(rawFindings.low),
      total: toNumber(rawFindings.total),
    },
    {
      lane: 'Fix Groups',
      critical: toNumber(fixGroupTotals.critical),
      high: toNumber(fixGroupTotals.high),
      medium: toNumber(fixGroupTotals.medium),
      low: toNumber(fixGroupTotals.low),
      total: toNumber(fixGroupTotals.total),
    },
    {
      lane: 'Most Critical',
      critical: mostCriticalCriticalTotal,
      high: mostCriticalHighTotal,
      medium: 0,
      low: 0,
      total: mostCriticalFindings.reduce((sum: number, row: any) => sum + toNumber(row?.total), 0),
    },
    {
      lane: 'Correlated',
      critical: correlatedCriticalTotal,
      high: correlatedHighTotal,
      medium: 0,
      low: 0,
      total: correlatedFindings.reduce((sum: number, row: any) => sum + toNumber(row?.total), 0),
    },
  ];

  const findingsSeriesData = (findingsSeries || []).map((row: any) => ({
    period: String(row?.period || ''),
    critical: toNumber(row?.critical),
    high: toNumber(row?.high),
    medium: toNumber(row?.medium),
    low: toNumber(row?.low),
    total: toNumber(row?.total),
  }));

  if (findingsSeriesData.length === 0) {
    findingsSeriesData.push(
      ...(trend || []).map((row: any, idx: number) => ({
        period: String(row?.month || row?.period || `P${idx + 1}`),
        critical: 0,
        high: 0,
        medium: 0,
        low: 0,
        total: toNumber(row?.issues || row?.total || 0),
      })),
    );
  }

  const scanSeriesData = (scanSeries || []).map((row: any) => ({
    period: String(row?.period || ''),
    critical: toNumber(row?.critical),
    high: toNumber(row?.high),
    medium: toNumber(row?.medium),
    low: toNumber(row?.low),
    total: toNumber(row?.total),
  }));

  if (scanSeriesData.length === 0) {
    scanSeriesData.push({ period: scanPeriod, critical: 0, high: 0, medium: 0, low: 0, total: 0 });
  }

  const cumulativeTrendData = Array.isArray(workbenchTrends?.cumulative_vulnerabilities)
    ? workbenchTrends.cumulative_vulnerabilities.map((row: any) => ({
      period: String(row?.period || ''),
      monthly_total: toNumber(row?.monthly_total),
      cumulative_total: toNumber(row?.cumulative_total),
    }))
    : [];

  if (cumulativeTrendData.length === 0) {
    let running = 0;
    (trend || []).forEach((row: any) => {
      const monthly = toNumber(row?.issues || 0);
      running += monthly;
      cumulativeTrendData.push({
        period: String(row?.month || ''),
        monthly_total: monthly,
        cumulative_total: running,
      });
    });
  }

  const complianceTrendData = Array.isArray(workbenchTrends?.application_compliance)
    ? workbenchTrends.application_compliance.map((row: any) => ({
      period: String(row?.period || ''),
      total_apps: toNumber(row?.total_apps),
      compliant: toNumber(row?.compliant),
      non_compliant: toNumber(row?.non_compliant),
      compliance_rate: toNumber(row?.compliance_rate),
    }))
    : [];

  if (complianceTrendData.length === 0) {
    const fallbackTotal = applicationCount;
    complianceTrendData.push({
      period: new Date().toISOString().slice(0, 7),
      total_apps: fallbackTotal,
      compliant: fallbackTotal,
      non_compliant: 0,
      compliance_rate: fallbackTotal > 0 ? 100 : 0,
    });
  }

  const criticalityTrendData = Array.isArray(workbenchTrends?.vulnerabilities_criticality)
    ? workbenchTrends.vulnerabilities_criticality.map((row: any) => ({
      period: String(row?.period || ''),
      critical: toNumber(row?.critical),
      high: toNumber(row?.high),
      medium: toNumber(row?.medium),
      low: toNumber(row?.low),
      total: toNumber(row?.total),
    }))
    : [];

  if (criticalityTrendData.length === 0) {
    criticalityTrendData.push(...findingsSeriesData);
  }

  const applicationOnboardedData = Array.isArray(workbenchTrends?.application_onboarded)
    ? workbenchTrends.application_onboarded.map((row: any) => ({
      period: String(row?.period || ''),
      onboarded_count: toNumber(row?.onboarded_count),
      cumulative_onboarded: toNumber(row?.cumulative_onboarded),
    }))
    : [];

  if (applicationOnboardedData.length === 0) {
    applicationOnboardedData.push({
      period: new Date().toISOString().slice(0, 7),
      onboarded_count: applicationCount,
      cumulative_onboarded: applicationCount,
    });
  }

  const avgDaysResolveData = Array.isArray(workbenchTrends?.average_days_to_resolve)
    ? workbenchTrends.average_days_to_resolve.map((row: any) => ({
      period: String(row?.period || ''),
      average_days: toNumber(row?.average_days),
      fixed_count: toNumber(row?.fixed_count),
    }))
    : [];

  if (avgDaysResolveData.length === 0) {
    avgDaysResolveData.push({
      period: new Date().toISOString().slice(0, 7),
      average_days: 0,
      fixed_count: 0,
    });
  }

  const licensePayload = workbenchTrends?.license_consumption || {};
  const licenseModelLabel = String(
    licensePayload?.detected_model_label || licensePayload?.detected_model || 'Unknown',
  );
  const licenseModelSource = String(licensePayload?.model_source || 'unknown');
  const licenseConsumptionData = Array.isArray(licensePayload?.technologies)
    ? licensePayload.technologies.map((row: any) => ({
      technology: String(row?.technology || 'UNKNOWN').toUpperCase(),
      consumed_units: toNumber(row?.consumed_units),
      consumed_scans: toNumber(row?.consumed_scans),
      consumed_apps: toNumber(row?.consumed_apps),
      peak_concurrent: toNumber(row?.peak_concurrent),
    }))
    : [];

  if (licenseConsumptionData.length === 0) {
    licenseConsumptionData.push(
      { technology: 'DAST', consumed_units: 0, consumed_scans: 0, consumed_apps: 0, peak_concurrent: 0 },
      { technology: 'SAST', consumed_units: 0, consumed_scans: 0, consumed_apps: 0, peak_concurrent: 0 },
      { technology: 'SCA', consumed_units: 0, consumed_scans: 0, consumed_apps: 0, peak_concurrent: 0 },
      { technology: 'IAST', consumed_units: 0, consumed_scans: 0, consumed_apps: 0, peak_concurrent: 0 },
    );
  }

  const scanTimePayload = workbenchTrends?.scan_time_trend || {};
  const scanTimePeriodOptions = Array.isArray(scanTimePayload?.period_options)
    ? scanTimePayload.period_options
      .map((value: any) => String(value || '').toLowerCase())
      .filter((value: string) => ['week', 'month', 'year'].includes(value))
    : [];
  const scanTimeBucketOptions = Array.isArray(scanTimePayload?.bucket_options)
    ? scanTimePayload.bucket_options
      .map((item: any) => ({
        key: String(item?.key || ''),
        label: String(item?.label || item?.key || ''),
      }))
      .filter((item: any) => item.key)
    : [];

  const fallbackScanTimePeriodOptions: ScanTimeBucketPeriod[] = ['week', 'month', 'year'];
  const fallbackScanTimeBucketOptions = [
    { key: 'lt5', label: '<5m' },
    { key: 'm5_10', label: '5-10m' },
    { key: 'm10_30', label: '10-30m' },
    { key: 'm30_60', label: '30-60m' },
    { key: 'm60_120', label: '60-120m' },
    { key: 'm120_240', label: '120-240m' },
    { key: 'm240_300', label: '240-300m' },
    { key: 'gte300', label: '>=300m' },
  ];

  const effectiveScanTimePeriodOptions = (scanTimePeriodOptions.length > 0
    ? scanTimePeriodOptions
    : fallbackScanTimePeriodOptions) as ScanTimeBucketPeriod[];
  const effectiveScanTimeBucketOptions = scanTimeBucketOptions.length > 0
    ? scanTimeBucketOptions
    : fallbackScanTimeBucketOptions;

  const defaultScanTimePeriod = String(scanTimePayload?.default_period || 'month').toLowerCase() as ScanTimeBucketPeriod;
  const effectiveScanTimePeriod = effectiveScanTimePeriodOptions.includes(scanTimeBucketPeriod)
    ? scanTimeBucketPeriod
    : (effectiveScanTimePeriodOptions.includes(defaultScanTimePeriod) ? defaultScanTimePeriod : effectiveScanTimePeriodOptions[0]);

  const defaultScanTimeBucket = String(scanTimePayload?.default_bucket || 'lt5');
  const effectiveScanTimeBucketKey = effectiveScanTimeBucketOptions.some((item: any) => item.key === scanTimeBucketKey)
    ? scanTimeBucketKey
    : (effectiveScanTimeBucketOptions.some((item: any) => item.key === defaultScanTimeBucket)
      ? defaultScanTimeBucket
      : effectiveScanTimeBucketOptions[0]?.key || 'lt5');

  const scanTimeByPeriod =
    scanTimePayload && typeof scanTimePayload.by_period === 'object' && scanTimePayload.by_period
      ? scanTimePayload.by_period
      : {};

  const scanTimePeriodRows = Array.isArray(scanTimeByPeriod?.[effectiveScanTimePeriod])
    ? scanTimeByPeriod[effectiveScanTimePeriod]
    : [];

  // All-buckets stacked bar data for Chart 1: each row has counts for all 8 duration buckets.
  const scanTimeBucketKeys = ['lt5', 'm5_10', 'm10_30', 'm30_60', 'm60_120', 'm120_240', 'm240_300', 'gte300'];
  const _getTimeBucketCount = (row: any, key: string, tech: 'total' | 'sast' | 'sca' | 'dast') => {
    const cell = row?.[key];
    if (!cell || typeof cell !== 'object') return 0;
    return toNumber(cell[tech] ?? cell.total);
  };
  const scanTimeBucketTrendData = scanTimePeriodRows.map((row: any) => {
    const tech = scanTimeTechFilter;
    return {
      period: String(row?.period || ''),
      lt5: _getTimeBucketCount(row, 'lt5', tech),
      m5_10: _getTimeBucketCount(row, 'm5_10', tech),
      m10_30: _getTimeBucketCount(row, 'm10_30', tech),
      m30_60: _getTimeBucketCount(row, 'm30_60', tech),
      m60_120: _getTimeBucketCount(row, 'm60_120', tech),
      m120_240: _getTimeBucketCount(row, 'm120_240', tech),
      m240_300: _getTimeBucketCount(row, 'm240_300', tech),
      gte300: _getTimeBucketCount(row, 'gte300', tech),
    };
  });

  if (scanTimeBucketTrendData.length === 0) {
    const fallbackPeriod = new Date().toISOString().slice(0, 7);
    scanTimeBucketKeys.reduce((acc, k) => { acc[k] = 0; return acc; },
      scanTimeBucketTrendData[scanTimeBucketTrendData.push({ period: fallbackPeriod } as any) - 1] as any);
  }

  const selectedScanTimeBucketLabel =
    effectiveScanTimeBucketOptions.find((item: any) => item.key === effectiveScanTimeBucketKey)?.label || effectiveScanTimeBucketKey;

  const sizeProfilePayload = workbenchTrends?.application_file_size_profile || {};
  const fallbackFileSizeBucketOptions = [
    { key: 'lt1', label: '<1MB', color: '#b91c1c' },
    { key: 'm1_5', label: '1-5MB', color: '#dc2626' },
    { key: 'm5_10', label: '5-10MB', color: '#ea580c' },
    { key: 'm10_20', label: '10-20MB', color: '#d97706' },
    { key: 'm20_100', label: '20-100MB', color: '#ca8a04' },
    { key: 'm100_500', label: '100-500MB', color: '#65a30d' },
    { key: 'm500_1g', label: '500MB-1GB', color: '#0f766e' },
    { key: 'gt1g', label: '>1GB', color: '#1d4ed8' },
  ];
  const fallbackFileSizeBucketColorMap = fallbackFileSizeBucketOptions.reduce<Record<string, string>>((acc, item) => {
    acc[item.key] = item.color;
    return acc;
  }, {});

  const fileSizePeriodOptions = Array.isArray(sizeProfilePayload?.period_options)
    ? sizeProfilePayload.period_options
      .map((value: any) => String(value || '').toLowerCase())
      .filter((value: string) => ['week', 'month', 'year'].includes(value))
    : [];

  const fileSizeBucketOptions = Array.isArray(sizeProfilePayload?.bucket_options)
    ? sizeProfilePayload.bucket_options
      .map((item: any) => {
        const key = String(item?.key || '');
        return {
          key,
          label: String(item?.label || item?.key || ''),
          color: String(item?.color || fallbackFileSizeBucketColorMap[key] || '#64748b'),
        };
      })
      .filter((item: any) => item.key)
    : [];

  const resolveFileSizeBucketKey = (row: any): string | null => {
    const key = String(row?.key || '').trim().toLowerCase();
    const bucketLabel = String(row?.bucket || '').trim().toLowerCase();
    const keyAliases: Record<string, string> = {
      lt1: 'lt1',
      m1_5: 'm1_5',
      m5_10: 'm5_10',
      m10_20: 'm10_20',
      m20_100: 'm20_100',
      m100_500: 'm100_500',
      m500_1g: 'm500_1g',
      gt1g: 'gt1g',
      m10_50: 'm20_100',
      m50_100: 'm20_100',
      m100_300: 'm100_500',
      m300_500: 'm100_500',
      m500_1000: 'm500_1g',
      gte1000: 'gt1g',
    };
    if (keyAliases[key]) {
      return keyAliases[key];
    }
    if (bucketLabel.includes('<1')) {
      return 'lt1';
    }
    if (bucketLabel.includes('1-5')) {
      return 'm1_5';
    }
    if (bucketLabel.includes('5-10')) {
      return 'm5_10';
    }
    if (bucketLabel.includes('10-20')) {
      return 'm10_20';
    }
    if (bucketLabel.includes('20-100')) {
      return 'm20_100';
    }
    if (bucketLabel.includes('100-500')) {
      return 'm100_500';
    }
    if (bucketLabel.includes('500') && (bucketLabel.includes('1gb') || bucketLabel.includes('1000'))) {
      return 'm500_1g';
    }
    if (bucketLabel.includes('>1gb') || bucketLabel.includes('>=1000')) {
      return 'gt1g';
    }
    return null;
  };

  const sizeBucketCounter = fallbackFileSizeBucketOptions.reduce<Record<string, { sast: number; sca: number }>>((acc, item) => {
    acc[item.key] = { sast: 0, sca: 0 };
    return acc;
  }, {});

  if (Array.isArray(sizeProfilePayload?.bins)) {
    sizeProfilePayload.bins.forEach((row: any) => {
      const bucketKey = resolveFileSizeBucketKey(row);
      if (!bucketKey || !sizeBucketCounter[bucketKey]) {
        return;
      }
      sizeBucketCounter[bucketKey].sast += toNumber(row?.sast);
      sizeBucketCounter[bucketKey].sca += toNumber(row?.sca);
    });
  }

  const effectiveFileSizePeriodOptions = (fileSizePeriodOptions.length > 0
    ? fileSizePeriodOptions
    : ['week', 'month', 'year']) as ScanTimeBucketPeriod[];
  const effectiveFileSizeBucketOptions = fileSizeBucketOptions.length > 0
    ? fileSizeBucketOptions
    : fallbackFileSizeBucketOptions;

  const defaultFileSizePeriod = String(sizeProfilePayload?.default_period || 'month').toLowerCase() as ScanTimeBucketPeriod;
  const effectiveFileSizePeriod = effectiveFileSizePeriodOptions.includes(fileSizeBucketPeriod)
    ? fileSizeBucketPeriod
    : (effectiveFileSizePeriodOptions.includes(defaultFileSizePeriod) ? defaultFileSizePeriod : effectiveFileSizePeriodOptions[0]);

  const defaultFileSizeBucket = String(sizeProfilePayload?.default_bucket || 'lt1');
  const effectiveFileSizeBucketKey = effectiveFileSizeBucketOptions.some((item: any) => item.key === fileSizeBucketKey)
    ? fileSizeBucketKey
    : (effectiveFileSizeBucketOptions.some((item: any) => item.key === defaultFileSizeBucket)
      ? defaultFileSizeBucket
      : effectiveFileSizeBucketOptions[0]?.key || 'lt1');

  const fileSizeByPeriod =
    sizeProfilePayload && typeof sizeProfilePayload.by_period === 'object' && sizeProfilePayload.by_period
      ? sizeProfilePayload.by_period
      : {};

  let fileSizePeriodRows = Array.isArray(fileSizeByPeriod?.[effectiveFileSizePeriod])
    ? fileSizeByPeriod[effectiveFileSizePeriod]
    : [];

  if (fileSizePeriodRows.length === 0) {
    const fallbackPeriod = new Date().toISOString().slice(0, 7);
    const fallbackRow: Record<string, any> = { period: fallbackPeriod };
    fallbackFileSizeBucketOptions.forEach((item) => {
      const counts = sizeBucketCounter[item.key] || { sast: 0, sca: 0 };
      fallbackRow[item.key] = {
        sast: counts.sast,
        sca: counts.sca,
        total: counts.sast + counts.sca,
      };
    });
    fileSizePeriodRows = [fallbackRow];
  }

  // All-buckets stacked bar data for Chart 2: each row has counts for all 8 size buckets.
  const fileSizeBucketKeys = ['lt1', 'm1_5', 'm5_10', 'm10_20', 'm20_100', 'm100_500', 'm500_1g', 'gt1g'];
  const _getSizeBucketCount = (row: any, key: string, tech: 'total' | 'sast' | 'sca') => {
    const cell = row?.[key];
    if (!cell || typeof cell !== 'object') return 0;
    return toNumber(cell[tech] ?? cell.total);
  };
  const fileSizeBucketTrendData = fileSizePeriodRows.map((row: any) => {
    const tech = fileSizeTechFilter;
    return {
      period: String(row?.period || ''),
      lt1: _getSizeBucketCount(row, 'lt1', tech),
      m1_5: _getSizeBucketCount(row, 'm1_5', tech),
      m5_10: _getSizeBucketCount(row, 'm5_10', tech),
      m10_20: _getSizeBucketCount(row, 'm10_20', tech),
      m20_100: _getSizeBucketCount(row, 'm20_100', tech),
      m100_500: _getSizeBucketCount(row, 'm100_500', tech),
      m500_1g: _getSizeBucketCount(row, 'm500_1g', tech),
      gt1g: _getSizeBucketCount(row, 'gt1g', tech),
    };
  });

  if (fileSizeBucketTrendData.length === 0) {
    fileSizeBucketTrendData.push({
      period: new Date().toISOString().slice(0, 7),
      lt1: 0, m1_5: 0, m5_10: 0, m10_20: 0, m20_100: 0, m100_500: 0, m500_1g: 0, gt1g: 0,
    });
  }

  const selectedFileSizeBucketLabel =
    effectiveFileSizeBucketOptions.find((item: any) => item.key === effectiveFileSizeBucketKey)?.label || effectiveFileSizeBucketKey;

  const coveragePayload = workbenchTrends?.top_dast_page_coverage || {};
  const fallbackDastCoverageBucketOptions = [
    { key: 'lt10', label: '<10' },
    { key: 'm10_50', label: '10-50' },
    { key: 'm50_100', label: '50-100' },
    { key: 'm100_500', label: '100-500' },
    { key: 'm500_1000', label: '500-1000' },
    { key: 'gte1000', label: '>=1000' },
  ];
  const fallbackDastCoverageBucketColorMap: Record<string, string> = {
    lt10: '#b91c1c',
    m10_50: '#dc2626',
    m50_100: '#ea580c',
    m100_500: '#d97706',
    m500_1000: '#65a30d',
    gte1000: '#0f766e',
  };

  const dastCoveragePeriodOptions = Array.isArray(coveragePayload?.period_options)
    ? coveragePayload.period_options
      .map((value: any) => String(value || '').toLowerCase())
      .filter((value: string) => ['week', 'month', 'year'].includes(value))
    : [];

  const dastCoverageBucketOptions = Array.isArray(coveragePayload?.bucket_options)
    ? coveragePayload.bucket_options
      .map((item: any) => {
        const key = String(item?.key || '');
        return {
          key,
          label: String(item?.label || item?.key || ''),
          color: String(item?.color || fallbackDastCoverageBucketColorMap[key] || '#64748b'),
        };
      })
      .filter((item: any) => item.key)
    : [];

  const effectiveDastCoveragePeriodOptions = (dastCoveragePeriodOptions.length > 0
    ? dastCoveragePeriodOptions
    : ['week', 'month', 'year']) as ScanTimeBucketPeriod[];
  const effectiveDastCoverageBucketOptions = dastCoverageBucketOptions.length > 0
    ? dastCoverageBucketOptions
    : fallbackDastCoverageBucketOptions;

  const defaultDastCoveragePeriod = String(coveragePayload?.default_period || 'month').toLowerCase() as ScanTimeBucketPeriod;
  const effectiveDastCoveragePeriod = effectiveDastCoveragePeriodOptions.includes(dastCoverageBucketPeriod)
    ? dastCoverageBucketPeriod
    : (effectiveDastCoveragePeriodOptions.includes(defaultDastCoveragePeriod)
      ? defaultDastCoveragePeriod
      : effectiveDastCoveragePeriodOptions[0]);

  const defaultDastCoverageBucket = String(coveragePayload?.default_bucket || 'lt10');
  const effectiveDastCoverageBucketKey = effectiveDastCoverageBucketOptions.some((item: any) => item.key === dastCoverageBucketKey)
    ? dastCoverageBucketKey
    : (effectiveDastCoverageBucketOptions.some((item: any) => item.key === defaultDastCoverageBucket)
      ? defaultDastCoverageBucket
      : effectiveDastCoverageBucketOptions[0]?.key || 'lt10');

  const resolveDastCoverageBucketKey = (row: any): string | null => {
    const key = String(row?.key || '').trim().toLowerCase();
    const bucketLabel = String(row?.bucket || '').trim().toLowerCase();
    const keyAliases: Record<string, string> = {
      lt10: 'lt10',
      m10_50: 'm10_50',
      m50_100: 'm50_100',
      m100_500: 'm100_500',
      m500_1000: 'm500_1000',
      gte1000: 'gte1000',
      m100_200: 'm100_500',
      m200_500: 'm100_500',
    };
    if (keyAliases[key]) {
      return keyAliases[key];
    }
    if (bucketLabel.includes('<10')) {
      return 'lt10';
    }
    if (bucketLabel.includes('10-50')) {
      return 'm10_50';
    }
    if (bucketLabel.includes('50-100')) {
      return 'm50_100';
    }
    if (bucketLabel.includes('100-500')) {
      return 'm100_500';
    }
    if (bucketLabel.includes('500-1000')) {
      return 'm500_1000';
    }
    if (bucketLabel.includes('>=1000') || bucketLabel.includes('>1000')) {
      return 'gte1000';
    }
    return null;
  };

  const dastCoverageBucketCounter = fallbackDastCoverageBucketOptions.reduce<Record<string, number>>((acc, item) => {
    acc[item.key] = 0;
    return acc;
  }, {});

  if (Array.isArray(coveragePayload?.bins)) {
    coveragePayload.bins.forEach((row: any) => {
      const bucketKey = resolveDastCoverageBucketKey(row);
      if (!bucketKey || dastCoverageBucketCounter[bucketKey] === undefined) {
        return;
      }
      dastCoverageBucketCounter[bucketKey] += toNumber(row?.count);
    });
  }

  const coverageByPeriod =
    coveragePayload && typeof coveragePayload.by_period === 'object' && coveragePayload.by_period
      ? coveragePayload.by_period
      : {};

  let dastCoveragePeriodRows = Array.isArray(coverageByPeriod?.[effectiveDastCoveragePeriod])
    ? coverageByPeriod[effectiveDastCoveragePeriod]
    : [];

  if (dastCoveragePeriodRows.length === 0) {
    const fallbackPeriod = new Date().toISOString().slice(0, 7);
    const fallbackRow: Record<string, any> = { period: fallbackPeriod };
    fallbackDastCoverageBucketOptions.forEach((item) => {
      fallbackRow[item.key] = {
        scan_count: dastCoverageBucketCounter[item.key] || 0,
      };
    });
    dastCoveragePeriodRows = [fallbackRow];
  }

  // All-buckets stacked bar data for Chart 3: each row has scan_count for all 6 page-coverage buckets.
  const dastCoverageTrendData = dastCoveragePeriodRows.map((row: any) => ({
    period: String(row?.period || ''),
    lt10: toNumber(row?.lt10?.scan_count ?? row?.lt10?.count),
    m10_50: toNumber(row?.m10_50?.scan_count ?? row?.m10_50?.count),
    m50_100: toNumber(row?.m50_100?.scan_count ?? row?.m50_100?.count),
    m100_500: toNumber(row?.m100_500?.scan_count ?? row?.m100_500?.count),
    m500_1000: toNumber(row?.m500_1000?.scan_count ?? row?.m500_1000?.count),
    gte1000: toNumber(row?.gte1000?.scan_count ?? row?.gte1000?.count),
  }));

  if (dastCoverageTrendData.length === 0) {
    dastCoverageTrendData.push({
      period: new Date().toISOString().slice(0, 7),
      lt10: 0, m10_50: 0, m50_100: 0, m100_500: 0, m500_1000: 0, gte1000: 0,
    });
  }

  const selectedDastCoverageBucketLabel =
    effectiveDastCoverageBucketOptions.find((item: any) => item.key === effectiveDastCoverageBucketKey)?.label
    || effectiveDastCoverageBucketKey;

  const rescannedData = Array.isArray(workbenchTrends?.most_frequently_rescanned)
    ? workbenchTrends.most_frequently_rescanned.map((row: any) => ({
      application: String(row?.application_name || row?.application_id || 'Unknown'),
      scan_count: toNumber(row?.scan_count),
    }))
    : [];

  if (rescannedData.length === 0) {
    rescannedData.push({ application: 'No data', scan_count: 0 });
  }
  const rescannedTop10Data = rescannedData.length
    ? rescannedData
    : [{ application: 'No data', scan_count: 0 }];

  const allComponents = pipelineBom
    .flatMap((pipeline) => (Array.isArray(pipeline?.components) ? pipeline.components : []))
    .map((component) => String(component).toLowerCase());
  const findTags = (keywords: string[]) => {
    const matches = allComponents.filter((component) => keywords.some((keyword) => component.includes(keyword)));
    return Array.from(new Set(matches)).slice(0, 5);
  };
  const coverageCards = [
    {
      title: 'Source Control',
      subtitle: 'Repositories and branch hooks',
      value: applicationCount,
      tags: findTags(['github', 'gitlab', 'bitbucket', 'azure repos', 'git']),
      tone: 'source',
    },
    {
      title: 'CI/CD',
      subtitle: 'Build and release security checks',
      value: pipelineBom.length,
      tags: findTags(['jenkins', 'github action', 'gitlab ci', 'azure devops', 'circleci']),
      tone: 'cicd',
    },
    {
      title: 'Registry',
      subtitle: 'Container and artifact controls',
      value: toNumber(scanTypeCounts.SCA),
      tags: findTags(['acr', 'ecr', 'gcr', 'docker', 'artifact']),
      tone: 'registry',
    },
    {
      title: 'Cloud Runtime',
      subtitle: 'Runtime posture observations',
      value: toNumber(scanTypeCounts.IAST + scanTypeCounts.DAST),
      tags: findTags(['aks', 'kubernetes', 'azure', 'aws', 'gcp']),
      tone: 'cloud',
    },
  ];

  const lastSyncCandidates = [
    freshness.statistics?.generated_at || freshness.statistics?.cached_at,
    freshness.portfolio?.generated_at || freshness.portfolio?.cached_at,
  ].filter(Boolean) as string[];
  const lastSyncEpochs = lastSyncCandidates
    .map((value) => new Date(value).getTime())
    .filter((value) => Number.isFinite(value));
  const lastSync = lastSyncEpochs.length > 0 ? new Date(Math.max(...lastSyncEpochs)) : null;

  const currentUserDisplayName =
    String(currentUser?.display_name || currentUser?.username || currentUser?.subject || '').trim() ||
    'Current User';
  const currentUserFirstName = String(currentUser?.first_name || '').trim();
  const currentUserLastName = String(currentUser?.last_name || '').trim();
  const currentUserEmail = String(currentUser?.email || '').trim() || 'Email unavailable';
  const currentUserRole = String(currentUser?.role || '').trim() || `Role ${authMode.toUpperCase()}`;
  const currentUserOrg =
    String(currentUser?.organization_name || currentUser?.tenant_name || '').trim() || 'Organization unavailable';
  const currentUserSource = String(currentUser?.source || 'local').toUpperCase();

  const allAccessibleAssetGroupIds = normalizeIdList(assetGroups.map((item) => String(item?.id || '')));
  const effectivePendingAssetGroupIds =
    pendingScopeFilters.assetGroupIds.length > 0 ? pendingScopeFilters.assetGroupIds : allAccessibleAssetGroupIds;
  const filteredAssetGroups = assetGroups.filter((item) => {
    const name = String(item?.name || '').toLowerCase();
    const needle = assetGroupSearch.trim().toLowerCase();
    return !needle || name.includes(needle);
  });
  const availableApplicationsForPendingScope = applications.filter((item) => {
    if (!scopeFiltersEnabled) {
      return true;
    }
    if (effectivePendingAssetGroupIds.length === 0) {
      return true;
    }
    return effectivePendingAssetGroupIds.includes(String(item?.asset_group_id || ''));
  });
  const filteredApplications = availableApplicationsForPendingScope.filter((item) => {
    const needle = applicationSearch.trim().toLowerCase();
    const name = String(item?.name || '').toLowerCase();
    return !needle || name.includes(needle);
  });
  const issueTechnologyOptions = (issueFilterOptions.technologies || []).map((item) => ({
    value: String(item?.value || '').toUpperCase(),
    label: String(item?.label || item?.value || '').toUpperCase(),
    count: toNumber(item?.count),
  }));
  const filteredVulnerabilityOptions = (issueFilterOptions.vulnerabilities || []).filter((item) => {
    const needle = vulnerabilitySearch.trim().toLowerCase();
    const label = String(item?.label || item?.value || '').toLowerCase();
    return !needle || label.includes(needle);
  });
  const isSingleAssetGroupScope = allAccessibleAssetGroupIds.length === 1;
  const scanTypeOptions = ['DAST', 'SAST', 'SCA', 'IAST', 'OTHER'];
  const scanStatusOptions = Array.from(
    new Set(['completed', 'running', 'pending', 'failed', ...Object.keys(statusBreakdown || {})]),
  ).filter(Boolean);

  const assetGroupNameMap = new Map(assetGroups.map((item) => [String(item?.id || ''), String(item?.name || item?.id || '')]));
  const applicationNameMap = new Map(
    applications.map((item) => [String(item?.id || ''), String(item?.name || item?.id || '')]),
  );

  const scopeChips: string[] = [];
  if (scopeFiltersEnabled) {
    const selectedAssetCount = normalizeIdList(appliedScopeFilters.assetGroupIds).length;
    if (selectedAssetCount > 0 && selectedAssetCount < allAccessibleAssetGroupIds.length) {
      const labels = appliedScopeFilters.assetGroupIds
        .slice(0, 3)
        .map((id) => assetGroupNameMap.get(id) || id);
      const extra = selectedAssetCount > 3 ? ` +${selectedAssetCount - 3}` : '';
      scopeChips.push(`Asset Groups: ${labels.join(', ')}${extra}`);
    }

    if (appliedScopeFilters.applicationIds.length > 0) {
      const labels = appliedScopeFilters.applicationIds
        .slice(0, 3)
        .map((id) => applicationNameMap.get(id) || id);
      const extra = appliedScopeFilters.applicationIds.length > 3 ? ` +${appliedScopeFilters.applicationIds.length - 3}` : '';
      scopeChips.push(`Applications: ${labels.join(', ')}${extra}`);
    }

    if (appliedScopeFilters.issueTechnologies.length > 0) {
      scopeChips.push(`Issue Tech: ${appliedScopeFilters.issueTechnologies.join(', ')}`);
    }

    if (appliedScopeFilters.vulnerabilities.length > 0) {
      const labels = appliedScopeFilters.vulnerabilities.slice(0, 2);
      const extra = appliedScopeFilters.vulnerabilities.length > 2 ? ` +${appliedScopeFilters.vulnerabilities.length - 2}` : '';
      scopeChips.push(`Vuln: ${labels.join(', ')}${extra}`);
    }

    if (appliedScopeFilters.scanTypes.length > 0) {
      scopeChips.push(`Scan Type: ${appliedScopeFilters.scanTypes.join(', ')}`);
    }

    if (appliedScopeFilters.scanStatuses.length > 0) {
      scopeChips.push(`Scan Status: ${appliedScopeFilters.scanStatuses.join(', ')}`);
    }

    if ((appliedScopeFilters.reportWindow || 'all') !== 'all') {
      scopeChips.push(`Report Window: ${appliedScopeFilters.reportWindow}`);
    }
  }

  async function applyScopeSelection(): Promise<void> {
    let nextAssetGroupIds = normalizeIdList(
      pendingScopeFilters.assetGroupIds.length > 0
        ? pendingScopeFilters.assetGroupIds
        : allAccessibleAssetGroupIds,
    );

    const assetNeedle = assetGroupSearch.trim().toLowerCase();
    if (scopePanel === 'assetGroups' && assetNeedle) {
      const visibleAssetGroupIds = new Set(
        filteredAssetGroups
          .map((item) => String(item?.id || ''))
          .filter(Boolean),
      );
      nextAssetGroupIds = nextAssetGroupIds.filter((id) => visibleAssetGroupIds.has(id));
    }

    if (scopeFiltersEnabled && nextAssetGroupIds.length === 0) {
      nextAssetGroupIds = normalizeIdList(allAccessibleAssetGroupIds);
    }

    let nextApplicationIds = normalizeIdList(pendingScopeFilters.applicationIds);
    const appNeedle = applicationSearch.trim().toLowerCase();
    if (scopePanel === 'applications' && appNeedle) {
      const visibleApplicationIds = new Set(
        filteredApplications
          .map((item) => String(item?.id || ''))
          .filter(Boolean),
      );
      nextApplicationIds = nextApplicationIds.filter((id) => visibleApplicationIds.has(id));
    }

    const allowedApplicationIds = new Set(
      availableApplicationsForPendingScope.map((item) => String(item?.id || '')).filter(Boolean),
    );

    let nextIssueTechnologies = normalizeStringList(
      pendingScopeFilters.issueTechnologies.map((item) => String(item || '').toUpperCase()),
    );
    if (scopePanel === 'issues') {
      const visibleTechnologyIds = new Set(
        issueTechnologyOptions
          .map((item) => String(item.value || '').toUpperCase())
          .filter(Boolean),
      );
      nextIssueTechnologies = normalizeStringList(
        nextIssueTechnologies.filter((item) => visibleTechnologyIds.has(item)),
      );
    }

    let nextVulnerabilities = normalizeStringList(
      pendingScopeFilters.vulnerabilities.map((item) => String(item || '').toLowerCase()),
    );
    const vulnNeedle = vulnerabilitySearch.trim().toLowerCase();
    if (scopePanel === 'issues' && vulnNeedle) {
      const visibleVulnerabilityIds = new Set(
        filteredVulnerabilityOptions
          .map((item: any) => String(item?.value || '').toLowerCase())
          .filter(Boolean),
      );
      nextVulnerabilities = nextVulnerabilities.filter((item) => visibleVulnerabilityIds.has(item));
    }

    const nextScanTypes = normalizeStringList(
      pendingScopeFilters.scanTypes.map((item) => String(item || '').toUpperCase()),
    );
    const nextScanStatuses = normalizeStringList(
      pendingScopeFilters.scanStatuses.map((item) => String(item || '').toLowerCase()),
    );

    const nextFilters: ScopeFilters = {
      assetGroupIds: nextAssetGroupIds,
      applicationIds: normalizeIdList(nextApplicationIds.filter((id) => allowedApplicationIds.has(id))),
      issueTechnologies: nextIssueTechnologies,
      vulnerabilities: nextVulnerabilities,
      scanTypes: nextScanTypes,
      scanStatuses: nextScanStatuses,
      reportWindow: pendingScopeFilters.reportWindow || 'all',
    };
    setAppliedScopeFilters(nextFilters);
    setPendingScopeFilters(nextFilters);
    await Promise.all([
      loadAnalytics(false, nextFilters),
      loadChartData(nextFilters),
    ]);
    if (scopePanel === 'issues') {
      await loadIssueFilterOptions(nextFilters, false);
    }
    setScopePanel(null);
  }

  async function clearScopeSelection(target: ScopePanel): Promise<void> {
    if (target === 'applications') {
      setApplicationSearch('');
      const next = { ...pendingScopeFilters, applicationIds: [] };
      setPendingScopeFilters(next);
      setAppliedScopeFilters(next);
      await Promise.all([
        loadAnalytics(false, next),
        loadChartData(next),
        (async () => {
          if (applications.length > 0) {
            return;
          }
          try {
            const applicationRows = await getList('/applications');
            setApplications(Array.isArray(applicationRows) ? applicationRows : []);
          } catch (err) {
            console.error(err);
          }
        })(),
      ]);
      return;
    }

    if (target === 'issues') {
      const next = {
        ...pendingScopeFilters,
        issueTechnologies: [],
        vulnerabilities: [],
      };
      setVulnerabilitySearch('');
      setPendingScopeFilters(next);
      setAppliedScopeFilters(next);
      await Promise.all([
        loadAnalytics(false, next),
        loadChartData(next),
        loadIssueFilterOptions(next, false),
      ]);
      return;
    }

    if (target === 'scans') {
      const next = {
        ...pendingScopeFilters,
        scanTypes: [],
        scanStatuses: [],
      };
      setPendingScopeFilters(next);
      setAppliedScopeFilters(next);
      await Promise.all([loadAnalytics(false, next), loadChartData(next)]);
      return;
    }

    if (target === 'reports') {
      const next = {
        ...pendingScopeFilters,
        reportWindow: 'all' as ReportWindow,
      };
      setPendingScopeFilters(next);
      setAppliedScopeFilters(next);
      await Promise.all([loadAnalytics(false, next), loadChartData(next)]);
      return;
    }

    const resetAssetGroups = normalizeIdList(allAccessibleAssetGroupIds);
    const next: ScopeFilters = {
      assetGroupIds: resetAssetGroups,
      applicationIds: [],
      issueTechnologies: pendingScopeFilters.issueTechnologies,
      vulnerabilities: pendingScopeFilters.vulnerabilities,
      scanTypes: pendingScopeFilters.scanTypes,
      scanStatuses: pendingScopeFilters.scanStatuses,
      reportWindow: pendingScopeFilters.reportWindow,
    };
    setPendingScopeFilters(next);
    setAppliedScopeFilters(next);
    await Promise.all([loadAnalytics(false, next), loadChartData(next)]);
  }

  const freshnessBadge = (domain: FreshnessDomain) => {
    const info = freshness[domain] || {};
    const source = String(info.source || 'cache').toLowerCase() === 'live' ? 'live' : 'cache';
    return (
      <span className={`tile-freshness-badge source-${source}`} title={`Updated ${formatFreshnessTime(info)}`}>
        {source.toUpperCase()} {formatFreshnessTime(info)}
      </span>
    );
  };
  return (
    <div className={`page page-overview mode-${viewMode}`}>
      <div className="overview-layout">
        <aside className="overview-sidebar">
          <div className="sidebar-brand">ASPM Console</div>
          <nav className="sidebar-nav">
            <button className={scopePanel === null ? 'sidebar-link active' : 'sidebar-link'} onClick={() => setScopePanel(null)}>
              Dashboard
            </button>
            <button
              className={scopePanel === 'applications' ? 'sidebar-link active' : 'sidebar-link'}
              onClick={() => setScopePanel((prev) => (prev === 'applications' ? null : 'applications'))}
              disabled={!scopeFiltersEnabled}
            >
              Applications{' '}
              <span>{appliedScopeFilters.applicationIds.length || applicationCount}</span>
            </button>
            <button
              className={scopePanel === 'assetGroups' ? 'sidebar-link active' : 'sidebar-link'}
              onClick={() => {
                setScopePanel((prev) => (prev === 'assetGroups' ? null : 'assetGroups'));
                setPendingScopeFilters((prev) => {
                  if (prev.assetGroupIds.length > 0) {
                    return prev;
                  }
                  return {
                    ...prev,
                    assetGroupIds: normalizeIdList(allAccessibleAssetGroupIds),
                  };
                });
              }}
              disabled={!scopeFiltersEnabled}
            >
              Asset Groups{' '}
              <span>{appliedScopeFilters.assetGroupIds.length || assetGroupCount}</span>
            </button>
            <button
              className={scopePanel === 'issues' ? 'sidebar-link active' : 'sidebar-link'}
              onClick={() => setScopePanel((prev) => (prev === 'issues' ? null : 'issues'))}
              disabled={!scopeFiltersEnabled}
            >
              Issues{' '}
              <span>
                {pendingScopeFilters.issueTechnologies.length + pendingScopeFilters.vulnerabilities.length || totalIssues}
              </span>
            </button>
            <button
              className={scopePanel === 'scans' ? 'sidebar-link active' : 'sidebar-link'}
              onClick={() => setScopePanel((prev) => (prev === 'scans' ? null : 'scans'))}
              disabled={!scopeFiltersEnabled}
            >
              Scans <span>{pendingScopeFilters.scanTypes.length + pendingScopeFilters.scanStatuses.length || totalScans}</span>
            </button>
            <button
              className={scopePanel === 'reports' ? 'sidebar-link active' : 'sidebar-link'}
              onClick={() => setScopePanel((prev) => (prev === 'reports' ? null : 'reports'))}
              disabled={!scopeFiltersEnabled}
            >
              Reports <span>{pendingScopeFilters.reportWindow === 'all' ? 'all' : pendingScopeFilters.reportWindow}</span>
            </button>
            <button
              className={scopePanel === 'endpoints' ? 'sidebar-link active' : 'sidebar-link'}
              onClick={() => setScopePanel((prev) => (prev === 'endpoints' ? null : 'endpoints'))}
            >
              Data Sources <span>{endpoints.length || '—'}</span>
            </button>
          </nav>
          {scopeFiltersEnabled && scopePanel === 'applications' ? (
            <section className="sidebar-filter-card">
              <header>
                <h4>Applications</h4>
                <span>{pendingScopeFilters.applicationIds.length || 'All'}</span>
              </header>
              <input
                className="sidebar-filter-search"
                placeholder="Search applications"
                value={applicationSearch}
                onChange={(e) => setApplicationSearch(e.target.value)}
              />
              <label className="sidebar-filter-option">
                <input
                  type="checkbox"
                  checked={pendingScopeFilters.applicationIds.length === 0}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setPendingScopeFilters((prev) => ({ ...prev, applicationIds: [] }));
                    }
                  }}
                />
                <span>All applications in selected asset groups</span>
              </label>
              <div className="sidebar-filter-list">
                {filteredApplications.map((item) => {
                  const id = String(item?.id || '');
                  const checked = pendingScopeFilters.applicationIds.includes(id);
                  return (
                    <label key={id} className="sidebar-filter-option">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => {
                          setPendingScopeFilters((prev) => {
                            if (e.target.checked) {
                              return {
                                ...prev,
                                applicationIds: normalizeIdList([...prev.applicationIds, id]),
                              };
                            }
                            return {
                              ...prev,
                              applicationIds: prev.applicationIds.filter((itemId) => itemId !== id),
                            };
                          });
                        }}
                      />
                      <span>{item?.name || id}</span>
                    </label>
                  );
                })}
                {filteredApplications.length === 0 ? (
                  <div className="sidebar-filter-empty" role="status">
                    {applicationSearch.trim()
                      ? 'No applications match your search in the current scope.'
                      : 'No applications are available in the current asset-group scope.'}
                  </div>
                ) : null}
              </div>
              <div className="sidebar-filter-actions">
                <button className="secondary" onClick={() => clearScopeSelection('applications')}>Clear</button>
                <button onClick={applyScopeSelection}>Apply</button>
              </div>
            </section>
          ) : null}
          {scopeFiltersEnabled && scopePanel === 'assetGroups' ? (
            <section className="sidebar-filter-card">
              <header>
                <h4>Asset Groups</h4>
                <span>{pendingScopeFilters.assetGroupIds.length || assetGroupCount}</span>
              </header>
              <input
                className="sidebar-filter-search"
                placeholder="Search asset groups"
                value={assetGroupSearch}
                onChange={(e) => setAssetGroupSearch(e.target.value)}
              />
              <label className="sidebar-filter-option">
                <input
                  type="checkbox"
                  checked={
                    allAccessibleAssetGroupIds.length > 0 &&
                    pendingScopeFilters.assetGroupIds.length === allAccessibleAssetGroupIds.length
                  }
                  disabled={isSingleAssetGroupScope}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setPendingScopeFilters((prev) => ({
                        ...prev,
                        assetGroupIds: normalizeIdList(allAccessibleAssetGroupIds),
                        applicationIds: prev.applicationIds.filter((appId) => {
                          const app = applications.find((item) => String(item?.id || '') === appId);
                          return app ? allAccessibleAssetGroupIds.includes(String(app?.asset_group_id || '')) : false;
                        }),
                      }));
                      return;
                    }

                    setPendingScopeFilters((prev) => ({
                      ...prev,
                      assetGroupIds: [],
                      applicationIds: [],
                    }));
                  }}
                />
                <span>All accessible asset groups</span>
              </label>
              <div className="sidebar-filter-list">
                {filteredAssetGroups.map((item) => {
                  const id = String(item?.id || '');
                  const checked = pendingScopeFilters.assetGroupIds.includes(id);
                  return (
                    <label key={id} className="sidebar-filter-option">
                      <input
                        type="checkbox"
                        disabled={isSingleAssetGroupScope}
                        checked={checked}
                        onChange={(e) => {
                          setPendingScopeFilters((prev) => {
                            const nextAssetIds = e.target.checked
                              ? normalizeIdList([...prev.assetGroupIds, id])
                              : prev.assetGroupIds.filter((itemId) => itemId !== id);
                            const normalizedAssetIds = nextAssetIds.length > 0 ? nextAssetIds : [];
                            const allowedGroupSet = new Set(
                              (normalizedAssetIds.length > 0 ? normalizedAssetIds : allAccessibleAssetGroupIds).map(String),
                            );
                            return {
                              ...prev,
                              assetGroupIds: normalizedAssetIds,
                              applicationIds: prev.applicationIds.filter((appId) => {
                                const app = applications.find((row) => String(row?.id || '') === appId);
                                return app ? allowedGroupSet.has(String(app?.asset_group_id || '')) : false;
                              }),
                            };
                          });
                        }}
                      />
                      <span>{item?.name || id}</span>
                    </label>
                  );
                })}
              </div>
              <div className="sidebar-filter-actions">
                <button className="secondary" onClick={() => clearScopeSelection('assetGroups')}>Clear</button>
                <button onClick={applyScopeSelection}>Apply</button>
              </div>
            </section>
          ) : null}
          {scopeFiltersEnabled && scopePanel === 'issues' ? (
            <section className="sidebar-filter-card">
              <header>
                <h4>Issues</h4>
                <span>
                  {pendingScopeFilters.issueTechnologies.length + pendingScopeFilters.vulnerabilities.length || 'All'}
                </span>
              </header>
              <div className="sidebar-filter-section-title">Testing Technology</div>
              <div className="sidebar-filter-subtitle">
                Unclassified issues: {toNumber(issueFilterOptions.unclassified_count)}
              </div>
              <label className="sidebar-filter-option">
                <input
                  type="checkbox"
                  checked={pendingScopeFilters.issueTechnologies.length === 0}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setPendingScopeFilters((prev) => ({ ...prev, issueTechnologies: [] }));
                    }
                  }}
                />
                <span>All technologies</span>
              </label>
              <div className="sidebar-filter-list compact">
                {issueTechnologyOptions.map((item) => {
                  const value = String(item.value || '').toUpperCase();
                  const checked = pendingScopeFilters.issueTechnologies.includes(value);
                  return (
                    <label key={value} className="sidebar-filter-option">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => {
                          setPendingScopeFilters((prev) => {
                            if (e.target.checked) {
                              return {
                                ...prev,
                                issueTechnologies: normalizeStringList([...prev.issueTechnologies, value]),
                              };
                            }
                            return {
                              ...prev,
                              issueTechnologies: prev.issueTechnologies.filter((row) => row !== value),
                            };
                          });
                        }}
                      />
                      <span>
                        {item.label} <em>({toNumber(item.count)})</em>
                      </span>
                    </label>
                  );
                })}
              </div>

              <div className="sidebar-filter-section-title">Vulnerability</div>
              <input
                className="sidebar-filter-search"
                placeholder="Search vulnerabilities"
                value={vulnerabilitySearch}
                onChange={(e) => setVulnerabilitySearch(e.target.value)}
              />
              <label className="sidebar-filter-option">
                <input
                  type="checkbox"
                  checked={pendingScopeFilters.vulnerabilities.length === 0}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setPendingScopeFilters((prev) => ({ ...prev, vulnerabilities: [] }));
                    }
                  }}
                />
                <span>All vulnerabilities</span>
              </label>
              <div className="sidebar-filter-list">
                {filteredVulnerabilityOptions.map((item: any) => {
                  const value = String(item?.value || '').toLowerCase();
                  const label = String(item?.label || item?.value || value);
                  const checked = pendingScopeFilters.vulnerabilities.includes(value);
                  return (
                    <label key={value} className="sidebar-filter-option">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => {
                          setPendingScopeFilters((prev) => {
                            if (e.target.checked) {
                              return {
                                ...prev,
                                vulnerabilities: normalizeStringList([...prev.vulnerabilities, value]),
                              };
                            }
                            return {
                              ...prev,
                              vulnerabilities: prev.vulnerabilities.filter((row) => row !== value),
                            };
                          });
                        }}
                      />
                      <span>
                        {label} <em>({toNumber(item?.count)})</em>
                      </span>
                    </label>
                  );
                })}
              </div>
              <div className="sidebar-filter-actions">
                <button className="secondary" onClick={() => clearScopeSelection('issues')}>Clear</button>
                <button onClick={applyScopeSelection}>Apply</button>
              </div>
            </section>
          ) : null}
          {scopeFiltersEnabled && scopePanel === 'scans' ? (
            <section className="sidebar-filter-card">
              <header>
                <h4>Scans</h4>
                <span>{pendingScopeFilters.scanTypes.length + pendingScopeFilters.scanStatuses.length || 'All'}</span>
              </header>

              <div className="sidebar-filter-section-title">Testing Technology</div>
              <label className="sidebar-filter-option">
                <input
                  type="checkbox"
                  checked={pendingScopeFilters.scanTypes.length === 0}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setPendingScopeFilters((prev) => ({ ...prev, scanTypes: [] }));
                    }
                  }}
                />
                <span>All scan technologies</span>
              </label>
              <div className="sidebar-filter-list compact">
                {scanTypeOptions.map((item) => {
                  const checked = pendingScopeFilters.scanTypes.includes(item);
                  return (
                    <label key={item} className="sidebar-filter-option">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => {
                          setPendingScopeFilters((prev) => {
                            if (e.target.checked) {
                              return {
                                ...prev,
                                scanTypes: normalizeStringList([...prev.scanTypes, item]),
                              };
                            }
                            return {
                              ...prev,
                              scanTypes: prev.scanTypes.filter((row) => row !== item),
                            };
                          });
                        }}
                      />
                      <span>{item}</span>
                    </label>
                  );
                })}
              </div>

              <div className="sidebar-filter-section-title">Scan Status</div>
              <label className="sidebar-filter-option">
                <input
                  type="checkbox"
                  checked={pendingScopeFilters.scanStatuses.length === 0}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setPendingScopeFilters((prev) => ({ ...prev, scanStatuses: [] }));
                    }
                  }}
                />
                <span>All scan statuses</span>
              </label>
              <div className="sidebar-filter-list compact">
                {scanStatusOptions.map((item) => {
                  const checked = pendingScopeFilters.scanStatuses.includes(item);
                  return (
                    <label key={item} className="sidebar-filter-option">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => {
                          setPendingScopeFilters((prev) => {
                            if (e.target.checked) {
                              return {
                                ...prev,
                                scanStatuses: normalizeStringList([...prev.scanStatuses, item]),
                              };
                            }
                            return {
                              ...prev,
                              scanStatuses: prev.scanStatuses.filter((row) => row !== item),
                            };
                          });
                        }}
                      />
                      <span>{item}</span>
                    </label>
                  );
                })}
              </div>
              <div className="sidebar-filter-actions">
                <button className="secondary" onClick={() => clearScopeSelection('scans')}>Clear</button>
                <button onClick={applyScopeSelection}>Apply</button>
              </div>
            </section>
          ) : null}
          {scopeFiltersEnabled && scopePanel === 'reports' ? (
            <section className="sidebar-filter-card">
              <header>
                <h4>Reports</h4>
                <span>{pendingScopeFilters.reportWindow === 'all' ? 'All history' : pendingScopeFilters.reportWindow}</span>
              </header>
              <div className="sidebar-filter-section-title">Reporting Window</div>
              {[
                { value: 'all', label: 'All history' },
                { value: '7d', label: 'Last 7 days' },
                { value: '30d', label: 'Last 30 days' },
                { value: '90d', label: 'Last 90 days' },
                { value: '365d', label: 'Last 365 days' },
              ].map((option) => (
                <label key={option.value} className="sidebar-filter-option">
                  <input
                    type="radio"
                    name="report-window"
                    checked={pendingScopeFilters.reportWindow === option.value}
                    onChange={() => {
                      setPendingScopeFilters((prev) => ({
                        ...prev,
                        reportWindow: option.value as ReportWindow,
                      }));
                    }}
                  />
                  <span>{option.label}</span>
                </label>
              ))}
              <div className="sidebar-filter-actions">
                <button className="secondary" onClick={() => clearScopeSelection('reports')}>Clear</button>
                <button onClick={applyScopeSelection}>Apply</button>
              </div>
            </section>
          ) : null}
          {scopePanel === 'endpoints' ? (
            <section className="sidebar-filter-card">
              <header>
                <h4>Data Sources</h4>
                <span>{endpoints.length}</span>
              </header>
              {endpoints.length === 0 ? (
                <div className="sidebar-filter-empty" role="status">
                  No ASoC endpoints configured.
                </div>
              ) : (
                <div className="sidebar-filter-list">
                  {endpoints.map((ep) => {
                    const statusEntry = endpointStatus?.find((r) => r.url === ep.url);
                    return (
                      <div key={ep.index} className="sidebar-filter-option" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '2px' }}>
                        <strong style={{ fontSize: '0.82rem' }}>{ep.label}</strong>
                        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted, #94a3b8)', wordBreak: 'break-all' }}>{ep.url}</span>
                        {statusEntry ? (
                          <span style={{ fontSize: '0.72rem', color: statusEntry.ok ? '#22c55e' : '#ef4444' }}>
                            {statusEntry.ok ? `✓ OK (${statusEntry.latency_ms}ms)` : `✗ ${statusEntry.error}`}
                          </span>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              )}
              <div className="sidebar-filter-actions">
                {(['PlatformAdmin', 'SecurityManager'].includes(currentUser?.role || '')) ? (
                  <button
                    onClick={async () => {
                      setEpModalError('');
                      setEpModalLoading(true);
                      try {
                        const result = await getManagedEndpoints();
                        setManagedEndpoints(result.endpoints || []);
                      } catch {
                        setManagedEndpoints([]);
                      } finally {
                        setEpModalLoading(false);
                      }
                      setEpEditIdx(null);
                      setEpForm({ url: '', label: '', api_key: '', api_secret: '' });
                      setEpModalOpen(true);
                    }}
                  >
                    Manage
                  </button>
                ) : null}
                {endpoints.length > 0 ? (
                  <button
                    className="secondary"
                    disabled={endpointStatusLoading}
                    onClick={async () => {
                      setEndpointStatusLoading(true);
                      setEndpointStatus(null);
                      try {
                        const result = await getEndpointStatus();
                        setEndpointStatus(result.results || []);
                      } catch (err) {
                        console.error('Endpoint status check failed', err);
                      } finally {
                        setEndpointStatusLoading(false);
                      }
                    }}
                  >
                    {endpointStatusLoading ? 'Checking...' : 'Check Status'}
                  </button>
                ) : null}
              </div>
            </section>
          ) : null}

          <div className="sidebar-current-user current-user-panel" aria-label="Current user profile">
            <span className="current-user-label">Signed In As</span>
            <strong className="current-user-name">{currentUserDisplayName}</strong>
            {(currentUserFirstName || currentUserLastName) && (
              <span className="current-user-meta" style={{ fontSize: '0.72rem', opacity: 0.8 }}>
                {[currentUserFirstName, currentUserLastName].filter(Boolean).join(' ')}
              </span>
            )}
            <span className="current-user-meta">{currentUserEmail}</span>
            <span className="current-user-meta" style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
              <span style={{ opacity: 0.6, fontSize: '0.68rem' }}>Role</span>
              {currentUserRole}
            </span>
            <span className="current-user-tenant" style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
              <span style={{ opacity: 0.6, fontSize: '0.68rem' }}>Org</span>
              {currentUserOrg}
            </span>
            <span className="current-user-source">{currentUserSource}</span>
          </div>
          <div className="sidebar-footnote">Scope-aware by role and accessible asset group.</div>
        </aside>

        <main className="overview-main">
          <header className="overview-topbar">
            <div>
              <h1>Security Operations Dashboard</h1>
              <p>Portfolio risk, posture, and pipeline activity in one view.</p>
            </div>
            <div className="topbar-meta">
              <div className="view-mode-toggle" role="tablist" aria-label="Dashboard view modes">
                {VIEW_MODE_OPTIONS.map((option) => (
                  <button
                    key={option.key}
                    className={viewMode === option.key ? 'view-mode-button active' : 'view-mode-button'}
                    onClick={() => setViewMode(option.key)}
                    aria-pressed={viewMode === option.key}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <button
                className="meta-chip refresh-chip"
                disabled={isRefreshingLive}
                onClick={async () => {
                  try {
                    setIsRefreshingLive(true);
                    await Promise.all([
                      loadAnalytics(true),
                      loadChartData(appliedScopeFilters),
                    ]);
                  } catch (err) {
                    console.error(err);
                  } finally {
                    setIsRefreshingLive(false);
                  }
                }}
              >
                {isRefreshingLive ? 'Refreshing...' : 'Refresh Live'}
              </button>
              <button
                className="meta-chip refresh-chip"
                onClick={async () => {
                  const nextEnabled = !scopeFiltersEnabled;
                  setScopeFiltersEnabled(nextEnabled);
                  setScopePanel(null);
                  if (!nextEnabled) {
                    const resetScope: ScopeFilters = {
                      assetGroupIds: [],
                      applicationIds: [],
                      issueTechnologies: [],
                      vulnerabilities: [],
                      scanTypes: [],
                      scanStatuses: [],
                      reportWindow: 'all',
                    };
                    setAppliedScopeFilters(resetScope);
                    setPendingScopeFilters(resetScope);
                    await Promise.all([
                      loadAnalytics(false, resetScope),
                      loadChartData(resetScope),
                    ]);
                    void loadIssueFilterOptions(resetScope, false).catch((err) => {
                      console.error(err);
                    });
                    return;
                  }
                  const defaultScope: ScopeFilters = {
                    assetGroupIds: normalizeIdList(assetGroups.map((item) => String(item?.id || ''))),
                    applicationIds: [],
                    issueTechnologies: [],
                    vulnerabilities: [],
                    scanTypes: [],
                    scanStatuses: [],
                    reportWindow: 'all',
                  };
                  setAppliedScopeFilters(defaultScope);
                  setPendingScopeFilters(defaultScope);
                  await Promise.all([
                    loadAnalytics(false, defaultScope),
                    loadChartData(defaultScope),
                  ]);
                  void loadIssueFilterOptions(defaultScope, false).catch((err) => {
                    console.error(err);
                  });
                }}
              >
                Scope Filters {scopeFiltersEnabled ? 'On' : 'Off'}
              </button>
              <span className="meta-chip">Auth {authMode.toUpperCase()}</span>
              <span className="meta-chip">Updated {lastSync ? lastSync.toLocaleTimeString() : 'n/a'}</span>
            </div>
          </header>

          {scopeFiltersEnabled ? (
            <section className="scope-chip-row" aria-label="Applied scope filters">
              {scopeChips.length > 0 ? (
                scopeChips.map((chip) => (
                  <span key={chip} className="scope-chip">{chip}</span>
                ))
              ) : (
                <span className="scope-chip muted">Scope: All accessible data</span>
              )}
            </section>
          ) : null}

          {authMode === 'oidc' ? (
            <section className="card token-card">
              <h2>OIDC External Token</h2>
              <div className="inline-form">
                <input
                  type="password"
                  placeholder="Paste bearer token"
                  value={externalToken}
                  onChange={(e) => setExternalToken(e.target.value)}
                />
                <button
                  onClick={() => {
                    setExternalBearerToken(externalToken);
                    globalThis.location.reload();
                  }}
                >
                  Apply Token
                </button>
              </div>
            </section>
          ) : null}

          {error ? <p className="error">{error}</p> : null}

          <section className={`card first-screen first-screen-${viewMode}`}>
            <div className="first-screen-header">
              <div>
                <h2>Issue Status and Prioritization</h2>
                <p>Threat pressure index based on active critical and high vulnerabilities.</p>
              </div>
              <div className="pressure-pill">Risk Pressure {riskPressure}%</div>
            </div>

            {viewMode === 'soc' ? (
              <div className="soc-alert-strip">
                <div>
                  <strong>SOC Alert Focus</strong>
                  <span>
                    Active issues: {activeIssues.toLocaleString()} | Critical: {severityBuckets.critical} | Failed scans: {failedScans}
                  </span>
                </div>
                <ul>
                  {(topFailedApps.length > 0 ? topFailedApps : [['No failing application detected', 0]]).map(([name, count]) => (
                    <li key={String(name)}>
                      {name} <em>{count} failed scans</em>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div className="impact-grid">
              <article className="impact-stat">
                <span>Total Issues</span>
                <strong>{totalIssues.toLocaleString()}</strong>
                <small style={{ color: 'var(--muted)', fontSize: '0.7rem', display: 'block', marginTop: '2px' }}>All statuses &amp; severities</small>
                {freshnessBadge('statistics')}
              </article>
              <article className="impact-stat">
                <span>Active Issues</span>
                <strong>{activeIssues.toLocaleString()}</strong>
                {freshnessBadge('statistics')}
              </article>
              <article className="impact-stat">
                <span>Resolved Issues</span>
                <strong>{resolvedIssues.toLocaleString()}</strong>
                {freshnessBadge('statistics')}
              </article>
              <article className="impact-stat">
                <span>Running or Pending Scans</span>
                <strong>{runningScans}</strong>
                {freshnessBadge('portfolio')}
              </article>
            </div>

            <div className="priority-row">
              <article className="priority-box critical">
                <span>Critical</span>
                <strong>{severityBuckets.critical}</strong>
                {freshnessBadge('statistics')}
              </article>
              <article className="priority-box high">
                <span>High</span>
                <strong>{severityBuckets.high}</strong>
                {freshnessBadge('statistics')}
              </article>
              <article className="priority-box medium">
                <span>Medium</span>
                <strong>{severityBuckets.medium}</strong>
                {freshnessBadge('statistics')}
              </article>
              <article className="priority-box low">
                <span>Low</span>
                <strong>{severityBuckets.low}</strong>
                {freshnessBadge('statistics')}
              </article>
              <article className="priority-box neutral">
                <span>Failed Scans</span>
                <strong>{failedScans}</strong>
                {freshnessBadge('portfolio')}
              </article>
            </div>

            <div className="center-chart-controls">
              <div className="center-chart-mode-toggle" role="tablist" aria-label="Center chart mode">
                <button
                  className={centerChartMode === 'prioritization' ? 'center-chart-button active' : 'center-chart-button'}
                  onClick={() => setCenterChartMode('prioritization')}
                >
                  Prioritization
                </button>
                <button
                  className={centerChartMode === 'findings' ? 'center-chart-button active' : 'center-chart-button'}
                  onClick={() => setCenterChartMode('findings')}
                >
                  Findings Over Time
                </button>
                <button
                  className={centerChartMode === 'scans' ? 'center-chart-button active' : 'center-chart-button'}
                  onClick={() => setCenterChartMode('scans')}
                >
                  Scans Over Time
                </button>
              </div>
              {centerChartMode === 'findings' || centerChartMode === 'scans' ? (
                <div className="center-chart-filter">
                  <span>Period</span>
                  {centerChartMode === 'findings' ? (
                    <select
                      value={findingsPeriod}
                      onChange={(e) => {
                        const nextPeriod = (e.target.value as FindingsPeriod) || 'month';
                        setFindingsPeriod(nextPeriod);
                      }}
                    >
                      <option value="week">Week</option>
                      <option value="month">Month</option>
                      <option value="year">Year</option>
                    </select>
                  ) : (
                    <>
                      <select
                        value={scanPeriod}
                        onChange={(e) => {
                          const nextPeriod = (e.target.value as ScanPeriod) || 'month';
                          setScanPeriod(nextPeriod);
                        }}
                      >
                        <option value="day">Day</option>
                        <option value="week">Week</option>
                        <option value="month">Month</option>
                      </select>
                      <span>Severity Source</span>
                      <select
                        value={scanSeveritySource}
                        onChange={(e) => {
                          const nextSource = (e.target.value as ScanSeveritySource) || 'hybrid';
                          setScanSeveritySource(nextSource);
                        }}
                      >
                        <option value="derived">Derived</option>
                        <option value="native">Native</option>
                        <option value="hybrid">Hybrid</option>
                      </select>
                    </>
                  )}
                </div>
              ) : null}
            </div>

            <div className="center-chart-grid">
              <div className="impact-chart-wrap center-chart-wrap">
                {centerChartMode === 'prioritization' ? (
                  <ResponsiveContainer width="100%" height={centerChartHeight}>
                    <BarChart data={prioritizationChartData}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="lane" />
                      <YAxis />
                      <Tooltip />
                      <Bar dataKey="critical" stackId="sev" fill="#b91c1c" />
                      <Bar dataKey="high" stackId="sev" fill="#ea580c" />
                      <Bar dataKey="medium" stackId="sev" fill="#ca8a04" />
                      <Bar dataKey="low" stackId="sev" fill="#0f766e" />
                      <Line type="monotone" dataKey="total" stroke="#1f2937" strokeWidth={2} dot={{ r: 2 }} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : centerChartMode === 'findings' ? (
                  <ResponsiveContainer width="100%" height={centerChartHeight}>
                    <AreaChart data={findingsSeriesData}>
                      <defs>
                        <linearGradient id="fg-critical" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#b91c1c" stopOpacity={0.55} />
                          <stop offset="95%" stopColor="#b91c1c" stopOpacity={0.06} />
                        </linearGradient>
                        <linearGradient id="fg-high" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#ea580c" stopOpacity={0.45} />
                          <stop offset="95%" stopColor="#ea580c" stopOpacity={0.04} />
                        </linearGradient>
                        <linearGradient id="fg-medium" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#d97706" stopOpacity={0.4} />
                          <stop offset="95%" stopColor="#d97706" stopOpacity={0.03} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="4 4" vertical={false} />
                      <XAxis dataKey="period" />
                      <YAxis />
                      <Tooltip />
                      <Area type="monotone" dataKey="critical" stroke="#b91c1c" fill="url(#fg-critical)" strokeWidth={2} />
                      <Area type="monotone" dataKey="high" stroke="#ea580c" fill="url(#fg-high)" strokeWidth={2} />
                      <Area type="monotone" dataKey="medium" stroke="#d97706" fill="url(#fg-medium)" strokeWidth={2} />
                      <Line type="monotone" dataKey="total" stroke="#1f2937" strokeWidth={2} dot={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <ResponsiveContainer width="100%" height={centerChartHeight}>
                    <LineChart data={scanSeriesData}>
                      <CartesianGrid strokeDasharray="4 4" vertical={false} />
                      <XAxis dataKey="period" />
                      <YAxis />
                      <Tooltip />
                      <Line type="monotone" dataKey="critical" stroke="#b91c1c" strokeWidth={2} dot={false} />
                      <Line type="monotone" dataKey="high" stroke="#ea580c" strokeWidth={2} dot={false} />
                      <Line type="monotone" dataKey="medium" stroke="#d97706" strokeWidth={2} dot={false} />
                      <Line type="monotone" dataKey="low" stroke="#0f766e" strokeWidth={2} dot={false} />
                      <Line type="monotone" dataKey="total" stroke="#1f2937" strokeWidth={2.5} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                )}
              </div>
            </div>

            {viewMode === 'large' ? (
              <div className="large-chart-grid">
                <div className="impact-chart-wrap secondary">
                  <ResponsiveContainer width="100%" height={250}>
                    <BarChart data={severityChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="severity" />
                      <YAxis />
                      <Tooltip />
                      <Bar dataKey="count">
                        {severityChartData.map((entry) => (
                          <Cell key={entry.severity} fill={entry.color} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="impact-chart-wrap secondary">
                  <ResponsiveContainer width="100%" height={250}>
                    <BarChart data={scanTypeChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="type" />
                      <YAxis />
                      <Tooltip />
                      <Bar dataKey="count" fill="#2563eb" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            ) : null}
          </section>

          <section className="card fabric-section">
            <h2>AppSec Coverage Fabric</h2>
            <div className="fabric-grid">
              {coverageCards.map((card) => (
                <article key={card.title} className={`fabric-card ${card.tone}`}>
                  <header>
                    <h3>{card.title}</h3>
                    <span>{card.value}</span>
                  </header>
                  <p>{card.subtitle}</p>
                  <div className="fabric-tags">
                    {(card.tags.length > 0 ? card.tags : ['No connector detected']).map((tag) => (
                      <span key={`${card.title}-${tag}`}>{tag}</span>
                    ))}
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className="asset-strip">
            <article>
              <span>Applications</span>
              <strong>{applicationCount}</strong>
              {freshnessBadge('portfolio')}
            </article>
            <article>
              <span>Asset Groups</span>
              <strong>{assetGroupCount}</strong>
              {freshnessBadge('portfolio')}
            </article>
            <article>
              <span>Total Scans</span>
              <strong>{totalScans}</strong>
              {freshnessBadge('portfolio')}
            </article>
            <article>
              <span>DAST</span>
              <strong>{scanTypeCounts.DAST}</strong>
              {freshnessBadge('portfolio')}
            </article>
            <article>
              <span>SAST</span>
              <strong>{scanTypeCounts.SAST}</strong>
              {freshnessBadge('portfolio')}
            </article>
            <article>
              <span>SCA</span>
              <strong>{scanTypeCounts.SCA}</strong>
              {freshnessBadge('portfolio')}
            </article>
            <article>
              <span>IAST</span>
              <strong>{scanTypeCounts.IAST}</strong>
              {freshnessBadge('portfolio')}
            </article>
          </section>

          <section className="workbench">
            <header className="workbench-header">
              <h2>Operations Workbench</h2>
              <p>Detailed analytics, automation, audit, and dashboard lifecycle controls.</p>
            </header>

          {/* ── Phase 3: Enhanced Analytics Charts ── */}
          <section className="chart-grid-new" style={{ marginTop: '1.5rem' }}>
            {/* Severity Donut */}
            <div className="chart-card-new">
              <h4>
                Issue Severity Distribution
                {issueCounts && (
                  <DataCompletenessIndicator
                    countSource={issueCounts.count_source || stats?.count_source}
                  />
                )}
              </h4>
              {issueCounts ? (
                <SeverityDonutChart
                  critical={issueCounts.critical || stats?.critical_issues || 0}
                  high={issueCounts.high || stats?.high_issues || 0}
                  medium={issueCounts.medium || stats?.medium_issues || 0}
                  low={issueCounts.low || stats?.low_issues || 0}
                />
              ) : (
                <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)' }}>
                  {chartDataLoading ? 'Loading…' : 'No data'}
                </div>
              )}
            </div>

            {/* Technology Breakdown */}
            <div className="chart-card-new">
              <h4>Issues by Technology</h4>
              {issueCounts ? (
                <TechnologyBarChart
                  sast={issueCounts.sast || 0}
                  dast={issueCounts.dast || 0}
                  sca={issueCounts.sca || 0}
                  iast={issueCounts.iast || 0}
                />
              ) : (
                <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)' }}>
                  {chartDataLoading ? 'Loading…' : 'No data'}
                </div>
              )}
            </div>

            {/* Status Distribution */}
            <div className="chart-card-new">
              <h4>Issues by Status</h4>
              {chartData?.status_distribution ? (
                <StatusDistributionChart statuses={chartData.status_distribution.statuses} />
              ) : (
                <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)' }}>
                  {chartDataLoading ? 'Loading…' : 'No data'}
                </div>
              )}
            </div>

            {/* Risk Heatmap */}
            <div className="chart-card-new">
              <h4>
                Risk Heatmap — Severity × Technology
                <small style={{ display: 'block', fontWeight: 400, color: 'var(--muted)', fontSize: '0.7rem', marginTop: '2px' }}>Critical–Low issues from issue list (all statuses)</small>
              </h4>
              {chartData?.risk_heatmap ? (
                <RiskHeatmap
                  matrix={chartData.risk_heatmap.matrix}
                  totals={chartData.risk_heatmap.totals}
                />
              ) : (
                <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)' }}>
                  {chartDataLoading ? 'Loading…' : 'No data'}
                </div>
              )}
            </div>

            {/* Top Applications */}
            <div className="chart-card-new chart-card-new--full">
              <h4>Top Applications by Issue Count</h4>
              {chartData?.top_apps ? (
                <TopAppsBarChart apps={chartData.top_apps.apps} />
              ) : (
                <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)' }}>
                  {chartDataLoading ? 'Loading…' : 'No data'}
                </div>
              )}
            </div>
          </section>

            <div className="workbench-grid">
              <section className="card chart-card">
                <h2>Issue Trend</h2>
                <ResponsiveContainer width="100%" height={320}>
                  <LineChart data={trend}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="month" />
                    <YAxis />
                    <Tooltip />
                    <Line type="monotone" dataKey="issues" stroke="#0f766e" strokeWidth={3} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </section>

              <section className="card chart-card">
                <h2>Scan Status</h2>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={statusChartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="status" />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="count">
                      {statusChartData.map((entry) => (
                        <Cell key={entry.status} fill={STATUS_COLORS[entry.status] || STATUS_COLORS.unknown} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </section>

              <section className="card chart-card">
                <h2>Cumulative Vulnerabilities Trend</h2>
                <ResponsiveContainer width="100%" height={320}>
                  <LineChart data={cumulativeTrendData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="period" />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Line type="monotone" dataKey="monthly_total" stroke="#0f766e" strokeWidth={2} dot={false} name="Monthly Findings" />
                    <Line type="monotone" dataKey="cumulative_total" stroke="#1f304a" strokeWidth={3} dot={false} name="Cumulative Findings" />
                  </LineChart>
                </ResponsiveContainer>
              </section>

              <section className="card chart-card">
                <h2>Application Compliant Status Trend</h2>
                <div className="chart-inline-controls">
                  <label>
                    Rule
                    <select
                      value={complianceRule}
                      onChange={(e) => setComplianceRule((e.target.value as ComplianceRule) || 'critical_high')}
                    >
                      <option value="critical_high">Critical/High</option>
                      <option value="any_open">Any Open Vulnerability</option>
                      <option value="custom">Custom Threshold</option>
                    </select>
                  </label>
                  {complianceRule === 'custom' ? (
                    <label>
                      Threshold
                      <select
                        value={complianceThreshold}
                        onChange={(e) => setComplianceThreshold((e.target.value as ComplianceThreshold) || 'high')}
                      >
                        <option value="critical">Critical</option>
                        <option value="high">High</option>
                        <option value="medium">Medium</option>
                        <option value="low">Low</option>
                      </select>
                    </label>
                  ) : null}
                </div>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={complianceTrendData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="period" />
                    <YAxis yAxisId="left" />
                    <YAxis yAxisId="right" orientation="right" domain={[0, 100]} />
                    <Tooltip />
                    <Legend />
                    <Bar yAxisId="left" dataKey="compliant" stackId="appStatus" fill="#0b8f6a" name="Compliant Apps" />
                    <Bar yAxisId="left" dataKey="non_compliant" stackId="appStatus" fill="#be123c" name="Non-Compliant Apps" />
                    <Line yAxisId="right" type="monotone" dataKey="compliance_rate" stroke="#1d4ed8" strokeWidth={2} dot={false} name="Compliance Rate %" />
                  </BarChart>
                </ResponsiveContainer>
              </section>

              <section className="card chart-card">
                <h2>Vulnerabilities Criticality Trend</h2>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={criticalityTrendData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="period" />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="critical" stackId="severity" fill="#b91c1c" name="Critical" />
                    <Bar dataKey="high" stackId="severity" fill="#ea580c" name="High" />
                    <Bar dataKey="medium" stackId="severity" fill="#ca8a04" name="Medium" />
                    <Bar dataKey="low" stackId="severity" fill="#0f766e" name="Low" />
                    <Line type="monotone" dataKey="total" stroke="#1f2937" strokeWidth={2} dot={false} name="Total" />
                  </BarChart>
                </ResponsiveContainer>
              </section>

              <section className="card chart-card">
                <h2>Application Onboarded Trend</h2>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={applicationOnboardedData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="period" />
                    <YAxis yAxisId="left" />
                    <YAxis yAxisId="right" orientation="right" />
                    <Tooltip />
                    <Legend />
                    <Bar yAxisId="left" dataKey="onboarded_count" fill="#0f766e" name="Onboarded in Month" />
                    <Line
                      yAxisId="right"
                      type="monotone"
                      dataKey="cumulative_onboarded"
                      stroke="#1f304a"
                      strokeWidth={2}
                      dot={false}
                      name="Cumulative Onboarded"
                    />
                  </BarChart>
                </ResponsiveContainer>
              </section>

              <section className="card chart-card">
                <h2>Average Days to Resolve Findings Trend</h2>
                <ResponsiveContainer width="100%" height={320}>
                  <LineChart data={avgDaysResolveData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="period" />
                    <YAxis yAxisId="left" />
                    <YAxis yAxisId="right" orientation="right" />
                    <Tooltip />
                    <Legend />
                    <Bar yAxisId="right" dataKey="fixed_count" fill="#93c5fd" name="Issues Fixed" />
                    <Line
                      yAxisId="left"
                      type="monotone"
                      dataKey="average_days"
                      stroke="#be123c"
                      strokeWidth={3}
                      dot={false}
                      name="Average Days"
                    />
                  </LineChart>
                </ResponsiveContainer>
              </section>

              <section className="card chart-card chart-card-tight-title">
                <h2>License Consumption by Technology</h2>
                <p className="chart-subtitle-small">Model: {licenseModelLabel} ({licenseModelSource})</p>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={licenseConsumptionData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="technology" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="consumed_apps" fill="#0f766e" name="Applications Tested" />
                    <Bar dataKey="consumed_scans" fill="#1d4ed8" name="Scans Executed" />
                  </BarChart>
                </ResponsiveContainer>
              </section>

              <section className="card chart-card chart-card-tight-title">
                <h2>Scan Time Bucket Trends</h2>
                <div className="chart-inline-controls">
                  <label>
                    Period
                    <select
                      value={effectiveScanTimePeriod}
                      onChange={(e) => setScanTimeBucketPeriod(e.target.value as ScanTimeBucketPeriod)}
                    >
                      {effectiveScanTimePeriodOptions.map((option) => (
                        <option key={option} value={option}>
                          {option.charAt(0).toUpperCase() + option.slice(1)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Technology
                    <select
                      value={scanTimeTechFilter}
                      onChange={(e) => setScanTimeTechFilter(e.target.value as 'total' | 'sast' | 'sca' | 'dast')}
                    >
                      <option value="total">All</option>
                      <option value="sast">SAST</option>
                      <option value="sca">SCA</option>
                      <option value="dast">DAST</option>
                    </select>
                  </label>
                </div>
                <p className="chart-subtitle-small">
                  Scan count by duration bucket over time
                </p>
                <ResponsiveContainer width="100%" height={290}>
                  <BarChart data={scanTimeBucketTrendData} margin={{ top: 8, right: 14, left: 2, bottom: 8 }}>
                    <CartesianGrid stroke="#d7dde8" strokeDasharray="3 3" vertical={false} />
                    <XAxis
                      dataKey="period"
                      tick={{ fontSize: 11 }}
                      tickMargin={8}
                      minTickGap={effectiveScanTimePeriod === 'week' ? 26 : 16}
                      interval="preserveStartEnd"
                      tickFormatter={(value) => formatScanTimePeriodTick(value, effectiveScanTimePeriod)}
                    />
                    <YAxis
                      tick={{ fontSize: 11 }}
                      tickMargin={6}
                      allowDecimals={false}
                      tickFormatter={(value) => toNumber(value).toLocaleString()}
                    />
                    <Tooltip
                      cursor={{ fill: 'rgba(156,163,175,0.15)' }}
                      labelFormatter={(label) => formatScanTimePeriodLabel(label, effectiveScanTimePeriod)}
                      formatter={(value: any, name: any) => [toNumber(value).toLocaleString(), name]}
                      contentStyle={{
                        background: '#f8fafc',
                        border: '1px solid #cbd5e1',
                        borderRadius: 8,
                        boxShadow: '0 6px 16px rgba(15, 23, 42, 0.14)',
                        fontSize: 13,
                      }}
                      labelStyle={{ color: '#0f172a', fontWeight: 700, marginBottom: 4 }}
                      itemStyle={{ color: '#0f172a', paddingTop: 2, paddingBottom: 2 }}
                    />
                    <Legend wrapperStyle={{ fontSize: 11, paddingTop: 6 }} />
                    <Bar dataKey="lt5" stackId="a" name="<5m" fill="#3b82f6" />
                    <Bar dataKey="m5_10" stackId="a" name="5–10m" fill="#22c55e" />
                    <Bar dataKey="m10_30" stackId="a" name="10–30m" fill="#84cc16" />
                    <Bar dataKey="m30_60" stackId="a" name="30–60m" fill="#eab308" />
                    <Bar dataKey="m60_120" stackId="a" name="60–120m" fill="#f97316" />
                    <Bar dataKey="m120_240" stackId="a" name="120–240m" fill="#ef4444" />
                    <Bar dataKey="m240_300" stackId="a" name="240–300m" fill="#ec4899" />
                    <Bar dataKey="gte300" stackId="a" name="≥300m" fill="#a855f7" />
                  </BarChart>
                </ResponsiveContainer>
              </section>

              <section className="card chart-card chart-card-tight-title">
                <h2>SAST/SCA Scan Target Size Trends</h2>
                <div className="chart-inline-controls" style={{ marginBottom: 8 }}>
                  <label>
                    Period
                    <select
                      value={effectiveFileSizePeriod}
                      onChange={(e) => setFileSizeBucketPeriod(e.target.value as ScanTimeBucketPeriod)}
                    >
                      {effectiveFileSizePeriodOptions.map((option) => (
                        <option key={option} value={option}>
                          {option[0].toUpperCase() + option.slice(1)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Technology
                    <select
                      value={fileSizeTechFilter}
                      onChange={(e) => setFileSizeTechFilter(e.target.value as 'total' | 'sast' | 'sca')}
                    >
                      <option value="total">All</option>
                      <option value="sast">SAST</option>
                      <option value="sca">SCA</option>
                    </select>
                  </label>
                </div>
                <p className="chart-subtitle-small">
                  Scan count by target size bucket over time
                </p>
                <ResponsiveContainer width="100%" height={290}>
                  <BarChart data={fileSizeBucketTrendData} margin={{ top: 8, right: 14, left: 2, bottom: 8 }}>
                    <CartesianGrid stroke="#d7dde8" strokeDasharray="3 3" vertical={false} />
                    <XAxis
                      dataKey="period"
                      tick={{ fontSize: 11 }}
                      tickMargin={8}
                      minTickGap={effectiveFileSizePeriod === 'week' ? 26 : 16}
                      interval="preserveStartEnd"
                      tickFormatter={(value) => formatScanTimePeriodTick(value, effectiveFileSizePeriod)}
                    />
                    <YAxis
                      tick={{ fontSize: 11 }}
                      tickMargin={6}
                      allowDecimals={false}
                      tickFormatter={(value) => toNumber(value).toLocaleString()}
                    />
                    <Tooltip
                      cursor={{ fill: 'rgba(156,163,175,0.15)' }}
                      labelFormatter={(label) => formatScanTimePeriodLabel(label, effectiveFileSizePeriod)}
                      formatter={(value: any, name: any) => [toNumber(value).toLocaleString(), name]}
                      contentStyle={{
                        background: '#f8fafc',
                        border: '1px solid #cbd5e1',
                        borderRadius: 8,
                        boxShadow: '0 6px 16px rgba(15, 23, 42, 0.14)',
                        fontSize: 13,
                      }}
                      labelStyle={{ color: '#0f172a', fontWeight: 700, marginBottom: 4 }}
                      itemStyle={{ color: '#0f172a', paddingTop: 2, paddingBottom: 2 }}
                    />
                    <Legend wrapperStyle={{ fontSize: 11, paddingTop: 6 }} />
                    <Bar dataKey="lt1" stackId="a" name="<1MB" fill="#b91c1c" />
                    <Bar dataKey="m1_5" stackId="a" name="1–5MB" fill="#dc2626" />
                    <Bar dataKey="m5_10" stackId="a" name="5–10MB" fill="#ea580c" />
                    <Bar dataKey="m10_20" stackId="a" name="10–20MB" fill="#d97706" />
                    <Bar dataKey="m20_100" stackId="a" name="20–100MB" fill="#ca8a04" />
                    <Bar dataKey="m100_500" stackId="a" name="100–500MB" fill="#65a30d" />
                    <Bar dataKey="m500_1g" stackId="a" name="500MB–1GB" fill="#0f766e" />
                    <Bar dataKey="gt1g" stackId="a" name=">1GB" fill="#1d4ed8" />
                  </BarChart>
                </ResponsiveContainer>
              </section>

              <section className="card chart-card chart-card-tight-title">
                <h2>DAST Page Coverage Bucket Trends</h2>
                <div className="chart-inline-controls" style={{ marginBottom: 8 }}>
                  <label>
                    Period
                    <select
                      value={effectiveDastCoveragePeriod}
                      onChange={(e) => setDastCoverageBucketPeriod(e.target.value as ScanTimeBucketPeriod)}
                    >
                      {effectiveDastCoveragePeriodOptions.map((option) => (
                        <option key={option} value={option}>
                          {option[0].toUpperCase() + option.slice(1)}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <p className="chart-subtitle-small">
                  DAST scan count by page coverage bucket over time
                </p>
                <ResponsiveContainer width="100%" height={290}>
                  <BarChart data={dastCoverageTrendData} margin={{ top: 8, right: 14, left: 2, bottom: 8 }}>
                    <CartesianGrid stroke="#d7dde8" strokeDasharray="3 3" vertical={false} />
                    <XAxis
                      dataKey="period"
                      tick={{ fontSize: 11 }}
                      tickMargin={8}
                      minTickGap={effectiveDastCoveragePeriod === 'week' ? 26 : 16}
                      interval="preserveStartEnd"
                      tickFormatter={(value) => formatScanTimePeriodTick(value, effectiveDastCoveragePeriod)}
                    />
                    <YAxis
                      tick={{ fontSize: 11 }}
                      tickMargin={6}
                      allowDecimals={false}
                      tickFormatter={(value) => toNumber(value).toLocaleString()}
                    />
                    <Tooltip
                      cursor={{ fill: 'rgba(156,163,175,0.15)' }}
                      labelFormatter={(label) => formatScanTimePeriodLabel(label, effectiveDastCoveragePeriod)}
                      formatter={(value: any, name: any) => [toNumber(value).toLocaleString(), name]}
                      contentStyle={{
                        background: '#f8fafc',
                        border: '1px solid #cbd5e1',
                        borderRadius: 8,
                        boxShadow: '0 6px 16px rgba(15, 23, 42, 0.14)',
                        fontSize: 13,
                      }}
                      labelStyle={{ color: '#0f172a', fontWeight: 700, marginBottom: 4 }}
                      itemStyle={{ color: '#0f172a', paddingTop: 2, paddingBottom: 2 }}
                    />
                    <Legend wrapperStyle={{ fontSize: 11, paddingTop: 6 }} />
                    <Bar dataKey="lt10" stackId="a" name="<10 pages" fill="#b91c1c" />
                    <Bar dataKey="m10_50" stackId="a" name="10–50" fill="#ea580c" />
                    <Bar dataKey="m50_100" stackId="a" name="50–100" fill="#d97706" />
                    <Bar dataKey="m100_500" stackId="a" name="100–500" fill="#65a30d" />
                    <Bar dataKey="m500_1000" stackId="a" name="500–1000" fill="#0f766e" />
                    <Bar dataKey="gte1000" stackId="a" name="≥1000" fill="#1d4ed8" />
                  </BarChart>
                </ResponsiveContainer>
              </section>

              <section className="card chart-card chart-card-tight-title">
                <h2>Most Frequently Rescanned</h2>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={rescannedTop10Data} layout="vertical" margin={{ left: 12 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" tick={{ fontSize: 11 }} />
                    <YAxis
                      type="category"
                      dataKey="application"
                      width={140}
                      tick={{ fontSize: 10 }}
                      tickFormatter={(value) => compactLabel(value, 20)}
                    />
                    <Tooltip />
                    <Bar dataKey="scan_count" fill="#be123c" name="Rescan Count" />
                  </BarChart>
                </ResponsiveContainer>
              </section>

            </div>
          </section>
        </main>
      </div>
      {createPortal(
      epModalOpen ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Manage Data Sources"
          style={{
            position: 'fixed', inset: 0, zIndex: 9999,
            background: 'rgba(0,0,0,0.65)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            pointerEvents: 'auto',
          }}
          onClick={(e) => { if (e.target === e.currentTarget) setEpModalOpen(false); }}
        >
          <div style={{
            background: 'var(--bg-panel, #1e293b)',
            border: '1px solid var(--border, #334155)',
            borderRadius: '10px',
            padding: '1.5rem',
            width: '540px',
            maxWidth: '95vw',
            maxHeight: '90vh',
            overflowY: 'auto',
            color: 'var(--text, #f1f5f9)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <h3 style={{ margin: 0, fontSize: '1rem' }}>Manage Data Sources</h3>
              <button className="secondary" style={{ padding: '0.2rem 0.6rem' }} onClick={() => setEpModalOpen(false)}>✕</button>
            </div>

            {/* Existing endpoints list */}
            {managedEndpoints.length > 0 ? (
              <div style={{ marginBottom: '1.2rem' }}>
                <p style={{ fontSize: '0.78rem', color: 'var(--text-muted, #94a3b8)', marginBottom: '0.5rem' }}>Configured endpoints</p>
                {managedEndpoints.map((ep) => (
                  <div key={ep.index} style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '0.5rem 0.75rem', marginBottom: '0.4rem',
                    background: 'var(--bg-card, #0f172a)', borderRadius: '6px',
                    border: epEditIdx === ep.index ? '1px solid #3b82f6' : '1px solid var(--border, #334155)',
                  }}>
                    <div>
                      <strong style={{ fontSize: '0.82rem' }}>{ep.label}</strong>
                      <div style={{ fontSize: '0.72rem', color: 'var(--text-muted, #94a3b8)' }}>{ep.url}</div>
                      <div style={{ fontSize: '0.70rem', color: 'var(--text-muted, #94a3b8)' }}>Key: {ep.api_key || '—'} · Secret: {ep.has_secret ? '••••••' : '(none)'}</div>
                    </div>
                    <div style={{ display: 'flex', gap: '0.4rem' }}>
                      <button
                        className="secondary"
                        style={{ fontSize: '0.75rem', padding: '0.2rem 0.55rem' }}
                        onClick={() => {
                          setEpEditIdx(ep.index);
                          setEpForm({ url: ep.url, label: ep.label, api_key: ep.api_key, api_secret: '' });
                          setEpModalError('');
                        }}
                      >Edit</button>
                      <button
                        style={{ fontSize: '0.75rem', padding: '0.2rem 0.55rem', background: '#7f1d1d', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
                        onClick={async () => {
                          if (!confirm(`Delete "${ep.label}"?`)) return;
                          setEpModalLoading(true);
                          setEpModalError('');
                          try {
                            const result = await deleteEndpoint(ep.index);
                            setManagedEndpoints(result.endpoints || []);
                            const epList = await getEndpoints();
                            setEndpoints(epList.endpoints || []);
                          } catch (err: any) {
                            setEpModalError(err?.response?.data?.detail || 'Delete failed');
                          } finally {
                            setEpModalLoading(false);
                          }
                        }}
                      >Delete</button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p style={{ fontSize: '0.8rem', color: 'var(--text-muted, #94a3b8)', marginBottom: '1rem' }}>No endpoints configured yet.</p>
            )}

            {/* Add / Edit form */}
            <div style={{ borderTop: '1px solid var(--border, #334155)', paddingTop: '1rem' }}>
              <p style={{ fontSize: '0.78rem', color: 'var(--text-muted, #94a3b8)', marginBottom: '0.75rem' }}>
                {epEditIdx !== null ? `Editing endpoint #${epEditIdx}` : 'Add new endpoint'}
              </p>
              {epModalError ? (
                <div style={{ color: '#f87171', fontSize: '0.78rem', marginBottom: '0.6rem' }}>{epModalError}</div>
              ) : null}
              {[
                { field: 'label' as const, placeholder: 'e.g. US Cloud', label: 'Label' },
                { field: 'url' as const, placeholder: 'https://cloud.appscan.com', label: 'URL (https://)' },
                { field: 'api_key' as const, placeholder: 'API Key ID', label: 'API Key' },
                { field: 'api_secret' as const, placeholder: epEditIdx !== null ? 'Leave blank to keep existing' : 'API Key Secret', label: 'API Secret' },
              ].map(({ field, placeholder, label }) => (
                <div key={field} style={{ marginBottom: '0.6rem' }}>
                  <label style={{ display: 'block', fontSize: '0.75rem', marginBottom: '0.2rem', color: 'var(--text-muted, #94a3b8)' }}>{label}</label>
                  <input
                    type={field === 'api_secret' ? 'password' : 'text'}
                    value={epForm[field]}
                    placeholder={placeholder}
                    onChange={(e) => setEpForm((f) => ({ ...f, [field]: e.target.value }))}
                    style={{
                      width: '100%', boxSizing: 'border-box',
                      padding: '0.4rem 0.6rem', fontSize: '0.82rem',
                      background: 'var(--bg-input, #0f172a)',
                      border: '1px solid var(--border, #334155)',
                      borderRadius: '4px', color: 'inherit',
                    }}
                  />
                </div>
              ))}
              <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.8rem' }}>
                <button
                  disabled={epModalLoading}
                  onClick={async () => {
                    setEpModalError('');
                    setEpModalLoading(true);
                    try {
                      let result;
                      if (epEditIdx !== null) {
                        const payload: Record<string, string> = {};
                        if (epForm.url) payload.url = epForm.url;
                        if (epForm.label) payload.label = epForm.label;
                        if (epForm.api_key) payload.api_key = epForm.api_key;
                        if (epForm.api_secret) payload.api_secret = epForm.api_secret;
                        result = await updateEndpoint(epEditIdx, payload);
                      } else {
                        result = await createEndpoint({
                          url: epForm.url,
                          label: epForm.label,
                          api_key: epForm.api_key,
                          api_secret: epForm.api_secret,
                        });
                      }
                      setManagedEndpoints(result.endpoints || []);
                      const epList = await getEndpoints();
                      setEndpoints(epList.endpoints || []);
                      setEpEditIdx(null);
                      setEpForm({ url: '', label: '', api_key: '', api_secret: '' });
                    } catch (err: any) {
                      const detail = err?.response?.data?.detail;
                      setEpModalError(Array.isArray(detail)
                        ? detail.map((d: any) => d.msg).join('; ')
                        : (detail || 'Save failed'));
                    } finally {
                      setEpModalLoading(false);
                    }
                  }}
                >
                  {epModalLoading ? 'Saving...' : (epEditIdx !== null ? 'Update' : 'Add Endpoint')}
                </button>
                {epEditIdx !== null ? (
                  <button className="secondary" onClick={() => {
                    setEpEditIdx(null);
                    setEpForm({ url: '', label: '', api_key: '', api_secret: '' });
                    setEpModalError('');
                  }}>Cancel Edit</button>
                ) : null}
              </div>
              <p style={{ fontSize: '0.70rem', color: 'var(--text-muted, #94a3b8)', marginTop: '0.75rem' }}>
                Changes are saved to <code>.env</code> and take effect immediately — no restart required.
              </p>
            </div>
          </div>
        </div>
      ) : null,
      document.body
    )}
    </div>
  );
}
