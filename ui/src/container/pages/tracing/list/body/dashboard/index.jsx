import SpanLatencies from './span-latencies';
import TraceLatencies from './trace-latencies';
import TracesChart from './traces-chart';

function Dashboard() {
  return (
    <div className="flex flex-col gap-4">
      <TracesChart />

      <TraceLatencies />

      <SpanLatencies />
    </div>
  );
}

export default Dashboard;
