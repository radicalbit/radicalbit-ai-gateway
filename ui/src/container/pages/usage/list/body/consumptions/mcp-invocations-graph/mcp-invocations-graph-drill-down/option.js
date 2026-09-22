import chartTsToDate from '@Helpers/chart-ts-to-date';
import { CHART_COLORS } from '@Src/constants';

const GRANULARITY_TITLE = {
  hours: 'Hourly',
  days: 'Daily',
  weeks: 'Weekly',
  months: 'Monthly',
};

export default ({ xAxisData, series = [], granularity, total }) => {
  const granularityLabel = GRANULARITY_TITLE[granularity] || 'Weekly';

  return ({
    color: CHART_COLORS,
    title: {
      left: 35,
      top: 20,
      height: 50,
      text: `${granularityLabel} MCP Invocations: ${total ?? 0}`,
    },
    grid: {
      top: 80,
      right: 40,
      bottom: 40,
      left: 40,
      containLabel: true,
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
};
