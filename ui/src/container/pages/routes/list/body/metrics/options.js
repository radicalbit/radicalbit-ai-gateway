import ReactEChartsCore from 'echarts-for-react/lib/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import chartTsToDate from '@Helpers/chart-ts-to-date';

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

const GRANULARITY_LABEL = {
  hours: 'hour',
  days: 'day',
  weeks: 'week',
  months: 'month',
};

// Sparkline line colors from the design-system "Visualization Colors" (Light row).
const SPARKLINE_COLOR = {
  mostRequested: '#006FFA', // Chart 5 Light (blue)
  topCost: '#D16900', // Chart 4 Light (orange)
  topError: '#B61CD4', // Chart 2 Light (purple)
};

function sparklineOption(chart, formatter, color) {
  const isSinglePoint = chart.data.length === 1;

  return {
    grid: { top: 8, right: 8, bottom: 8, left: 8 },
    xAxis: {
      type: 'category',
      data: chart.timestamp,
      show: false,
      boundaryGap: false,
    },
    yAxis: {
      type: 'value',
      show: false,
    },
    series: [
      {
        type: 'line',
        data: chart.data,
        smooth: true,
        showSymbol: isSinglePoint,
        symbolSize: isSinglePoint ? 6 : 4,
        ...(color ? { itemStyle: { color } } : {}),
        lineStyle: { width: 2, ...(color ? { color } : {}) },
        areaStyle: { opacity: 0.1, ...(color ? { color } : {}) },
      },
    ],
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const { value, dataIndex } = params[0];
        const ts = chart.timestamp[dataIndex];
        const date = chartTsToDate({ ts, granularity: chart.granularity, type: 'tooltip' });
        return `${date}<br/><strong>${formatter(value)}</strong>`;
      },
    },
  };
}

function formatIncrement(value) {
  if (value === null || value === undefined) {
    return '--';
  }

  const sign = value >= 0 ? '+' : '';
  return `${sign}${Math.round(value)}%`;
}

export {
  GRANULARITY_LABEL, ReactEChartsCore, SPARKLINE_COLOR, echarts, formatIncrement, sparklineOption,
};
