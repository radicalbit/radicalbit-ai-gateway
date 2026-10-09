import chartTsToDate from '@Helpers/chart-ts-to-date';
import { CHART_COLORS } from '@Src/constants';
import * as echarts from 'echarts/core';
import { MCP_GROUP_BY } from '../group-by';

const DRILL_DOWN_ICON_ID = 'drill-down-icon';
const DRILL_DOWN_ICON_TYPE = 'drillDownTreeIcon';
const DRILL_DOWN_ICON_PATH = 'M8 5h13M13 12h8M13 19h8M3 10a2 2 0 0 0 2 2h3M3 5v12a2 2 0 0 0 2 2h3';

const DRILL_DOWN_SUBTEXT = {
  [MCP_GROUP_BY.groups.key]: 'Breakdown of the selected group',
  [MCP_GROUP_BY.credentials.key]: 'Breakdown of the selected credential',
  [MCP_GROUP_BY.services.key]: 'Breakdown of the selected MCP service',
};

echarts.graphic.registerShape(DRILL_DOWN_ICON_TYPE, echarts.graphic.extendPath(DRILL_DOWN_ICON_PATH));

const GRANULARITY_TITLE = {
  hours: 'Hourly',
  days: 'Daily',
  weeks: 'Weekly',
  months: 'Monthly',
};

export default ({ xAxisData, series = [], granularity, total, drillDownEntity }) => {
  const granularityLabel = GRANULARITY_TITLE[granularity] || 'Weekly';

  return ({
    color: CHART_COLORS,
    title: {
      left: 59,
      top: 20,
      height: 50,
      text: `${granularityLabel} MCP Invocations: ${total ?? 0}`,
      subtext: DRILL_DOWN_SUBTEXT[drillDownEntity] || '',
    },
    graphic: [{
      id: DRILL_DOWN_ICON_ID,
      type: DRILL_DOWN_ICON_TYPE,
      left: 35,
      top: 22,
      scaleX: 0.75,
      scaleY: 0.75,
      silent: true,
      style: {
        fill: 'none', lineWidth: 2, lineCap: 'round', lineJoin: 'round',
      },
    }],
    grid: {
      top: 95,
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
      minInterval: 1,
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
};
