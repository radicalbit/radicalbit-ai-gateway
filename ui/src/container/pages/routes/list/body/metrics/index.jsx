import RoutesCounter from './01-routes-counter';
import MostRequested from './02-most-requested';
import TopError from './03-top-error';
import TopCost from './04-top-cost';

function Metrics() {
  return (
    <div className="flex gap-8 p-8 overflow-x-auto">
      <RoutesCounter />

      <MostRequested />

      <TopError />

      <TopCost />
    </div>
  );
}

export default Metrics;
