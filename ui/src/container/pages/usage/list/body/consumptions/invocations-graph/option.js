import chartTsToDate from '@Helpers/chart-ts-to-date';
import { CHART_COLORS } from '@Src/constants';

export default ({ xAxisData, series = [], granularity, total }) => ({
  color: CHART_COLORS,
  title: {
    left: 35,
    top: 20,
    height: 50,
    text: `Models invocations: ${total}`,
  },
  grid: {
    top: 80,
    right: '25%',
    bottom: 40,
    left: 30,
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
    axisLine: {
      show: true,
      lineStyle: {
        color: '#e4e4dd',
        width: 1,
      },
    },
    axisLabel: {
      show: false,
    },
  },
  yAxis: {
    type: 'value',
    show: false,
  },
  series: series.map((s) => ({ type: 'bar', barMaxWidth: 35, barMinWidth: 8, ...s })),
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

      const totalRequests = params.reduce((sum, p) => sum + p.value, 0);

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

          <div><b>Total: ${totalRequests}</b></div>
        </div>
      `;
    },
  },
});
