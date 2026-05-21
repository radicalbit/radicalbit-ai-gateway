import ReactEChartsCore from 'echarts-for-react/lib/core';
import { BarChart } from 'echarts/charts';
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import chartTsToDate from '@Helpers/chart-ts-to-date';

echarts.use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer, TitleComponent]);

const SERIES_COLOR_MAP = {
  success: '#4db694', // var(--coo-success)
  warning: '#ff7a00', // var(--coo-warning)
  error: '#f60000', // var(--coo-error)
};

const GRANULARITY_LABEL = {
  hours: 'hour',
  days: 'day',
  weeks: 'week',
  months: 'month',
};

function tracesBarChartOption({ xAxisData, series = [], granularity, total }) {
  return {
    title: {
      left: 35,
      top: 20,
      height: 50,
      textStyle: {
        fontSize: '1.5rem',
      },
      text: (() => {
        switch (granularity) {
          case 'days':
            return `Daily Traces: ${total}`;
          case 'weeks':
            return `Weekly Traces: ${total}`;
          case 'months':
            return `Monthly Traces: ${total}`;
          default:
            return `Hourly Traces: ${total}`;
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
    series: series.map((s) => {
      const color = SERIES_COLOR_MAP[s.name.toLowerCase()];
      return {
        type: 'bar',
        stack: 'total',
        barMaxWidth: 35,
        barMinWidth: 8,
        ...(color ? { itemStyle: { color }, color } : {}),
        ...s,
      };
    }),
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
            <div><b>Total: ${totalNum}</b></div>
          </div>
        `;
      },
    },
  };
}

export { GRANULARITY_LABEL, ReactEChartsCore, echarts, tracesBarChartOption };
