import {
  useGetSpanLatenciesWithRange,
  useGetTraceLatenciesWithRange,
  useGetTracesChartWithRange,
} from '@State/tracing/vertical-hooks';
import { Skeleton } from '@radicalbit/radicalbit-design-system';
import SpanLatencies from './span-latencies';
import TraceLatencies from './trace-latencies';
import TracesChart from './traces-chart';

function Dashboard() {
  const { isLoading: isLoadingChart } = useGetTracesChartWithRange();
  const { isLoading: isLoadingTraceLatencies } = useGetTraceLatenciesWithRange();
  const { isLoading: isLoadingSpanLatencies } = useGetSpanLatenciesWithRange({ grouped: true });

  if (isLoadingChart || isLoadingTraceLatencies || isLoadingSpanLatencies) {
    return <Skeleton.Node active style={{ height: '20rem', width: '100%' }} />;
  }

  return (
    <div className="flex flex-col gap-4">
      <TracesChart />

      <TraceLatencies />

      <SpanLatencies />
    </div>
  );
}

export default Dashboard;
