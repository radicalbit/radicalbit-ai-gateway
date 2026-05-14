import chartTsToDate from '@Helpers/chart-ts-to-date';
import { CHART_COLORS } from '@Src/constants';
import costFormatter from '@Helpers/cost-formatter';

const GRANULARITY_TITLE = {
  hours: 'Hourly',
  days: 'Daily',
  weeks: 'Weekly',
  months: 'Monthly',
};

export default ({ xAxisData, series = [], granularity, total }) => {
  const formattedTotal = costFormatter({ cent: total });
  const granularityLabel = GRANULARITY_TITLE[granularity] || 'Hourly';

  return ({
    color: CHART_COLORS,
    title: {
      left: 35,
      top: 20,
      height: 50,
      text: `${granularityLabel} Costs: ${formattedTotal}`,
    },
    grid: {
      top: 80,
      right: '20%',
      bottom: 40,
      left: 40,
      containLabel: true,
    },
    legend: {
      type: 'scroll',
      orient: 'vertical',
      right: '5%',
      top: '20%',
      formatter: (name) => name,
    },
    xAxis: {
      type: 'category',
      data: xAxisData,
      axisLabel: {
        rotate: 45,
        interval: 0,
        formatter(value) {
          return chartTsToDate({ ts: value, granularity, type: 'xaxis' });
        },
      },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        formatter(value) {
          const num = Number(value);

          if (num < 1) {
            return `$${num.toFixed(4)}`;
          }

          return `$${num.toFixed(2)}`;
        },
      },
    },
    series: series.map((s) => ({ type: 'bar', stack: 'total', barMaxWidth: 35, barMinWidth: 8, ...s })),
    tooltip: {
      enterable: false,
      confine: true,
      trigger: 'axis',
      axisPointer: {
        type: 'shadow',
      },
      formatter(params) {
        const ts = parseInt(params[0].axisValue, 10);
        const dateStr = chartTsToDate({ ts, granularity, type: 'tooltip' });

        const totalNum = params.reduce((sum, p) => sum + p.value, 0);
        const totalStr = costFormatter({ cent: totalNum });

        const rows = params
          .filter((p) => !!p.value)
          .map((p) => {
            const valueStr = costFormatter({ cent: p.value });

            return `
          <tr>
            <td style="padding-right:8px;">${p.marker}${p.seriesName}</td>
            <td style="text-align:right;">${valueStr}</td>
          </tr>
        `;
          }).join('');

        return `
        <div>
          <div>${dateStr}</div>

          <br/>

          <table>
            <tbody>
              ${rows}
            </tbody>
          </table>

          <br/>

          <div><b>Total: ${totalStr}</b></div>
        </div>
      `;
      },
    },
  });
};
