import chartTsToDate from '@Helpers/chart-ts-to-date';

const getValue = (point) => (typeof point === 'object' && point !== null ? point.value : point);

function ChartData({ granularity, series = [], xAxisData = [] }) {
  if (!xAxisData.length || !series.length) {
    return false;
  }

  return (
    <details className="mt-2 text-xs">
      <summary className="cursor-pointer w-fit">Show data</summary>

      <div className="max-h-64 overflow-auto mt-2">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="text-left p-1" scope="col">Time</th>

              {series.map(({ name }) => <th key={name} className="text-right p-1" scope="col">{name}</th>)}
            </tr>
          </thead>

          <tbody>
            {xAxisData.map((ts, index) => (
              <tr key={ts}>
                <th className="text-left p-1 font-normal" scope="row">{chartTsToDate({ ts, granularity, type: 'tooltip' })}</th>

                {series.map(({ data, name }) => <td key={name} className="text-right p-1">{getValue(data?.[index]) ?? '--'}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export default ChartData;
