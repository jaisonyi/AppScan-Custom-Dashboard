interface DataCompletenessProps {
  countSource?: string;
  totalFromApi?: number;
  totalFetched?: number;
}

export default function DataCompletenessIndicator({
  countSource,
  totalFromApi,
  totalFetched,
}: DataCompletenessProps) {
  if (countSource === 'api_count') {
    return (
      <span
        className="data-completeness data-completeness--accurate"
        title="Counts sourced from API /Count endpoints — accurate"
      >
        ✓ Accurate counts
      </span>
    );
  }

  if (totalFromApi && totalFetched && totalFetched < totalFromApi) {
    const pct = ((totalFetched / totalFromApi) * 100).toFixed(1);
    return (
      <span
        className="data-completeness data-completeness--truncated"
        title={`Only ${totalFetched.toLocaleString()} of ${totalFromApi.toLocaleString()} issues fetched (${pct}%)`}
      >
        ⚠ Showing {totalFetched.toLocaleString()} of {totalFromApi.toLocaleString()} ({pct}%)
      </span>
    );
  }

  return null;
}
