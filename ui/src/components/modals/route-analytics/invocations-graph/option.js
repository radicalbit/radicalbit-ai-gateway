import chartTsToDate from '@Helpers/chart-ts-to-date';
import { CHART_COLORS } from '@Src/constants';

export default ({ xAxisData, series = [], granularity, total }) => ({
  color: CHART_COLORS,
  title: {
    left: 35,
    top: 20,
    height: 50,
    text: (() => {
      switch (granularity) {
        case 'days':
          return `Daily Invocations: ${total}`;
        case 'weeks':
          return `Weekly Invocations: ${total}`;
        case 'months':
          return `Monthly Invocations: ${total}`;
        default:
          return `Hourly Invocations: ${total}`;
      }
    })(),
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
    top: '25%',
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
    minInterval: 1,
    axisLabel: {
      formatter(value) {
        return Math.round(value);
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

      const totalInvocations = params.reduce((sum, p) => sum + p.value, 0);

      const rows = params
        .filter((p) => !!p.value)
        .map((p) => `
          <tr>
            <td style="padding-right:8px;">${p.marker}${p.seriesName}</td>
            <td style="text-align:right;">${p.value}</td>
          </tr>
        `).join('');

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

          <div><b>Total: ${totalInvocations}</b></div>
        </div>
      `;
    },
  },
});
