import chartTsToDate from '@Helpers/chart-ts-to-date';
import { CHART_COLORS } from '@Src/constants';
import costFormatter from '@Helpers/cost-formatter';

const GRANULARITY_TITLE = {
  hours: 'Hourly',
  days: 'Daily',
  weeks: 'Weekly',
  months: 'Monthly',
};

export default ({ xAxisData, series = [], granularity, total, routeBreakdownCache }) => {
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
      trigger: 'item',
      formatter(params) {
        const ts = parseInt(params.name, 10);
        const dateStr = chartTsToDate({ ts, granularity, type: 'tooltip' });
        const cacheKey = `${params.seriesName}:${params.name}`;
        const cached = routeBreakdownCache ? routeBreakdownCache.get(cacheKey) : undefined;

        const segmentValue = costFormatter({ cent: params.value });

        if (cached === 'loading') {
          return `
          <div>
            <div>${dateStr}</div>
            <br/>
            <div>${params.marker}${params.seriesName}</div>
            <br/>
            <div class="color-secondary-01">Loading…</div>
            <br/>
            <div><b>Total: ${segmentValue}</b></div>
          </div>
        `;
        }

        if (cached === 'error') {
          return `
          <div>
            <div>${dateStr}</div>
            <br/>
            <div>${params.marker}${params.seriesName}</div>
            <br/>
            <div class="is-error">Unable to load breakdown</div>
            <div class="color-secondary-01" style="font-size:0.85em;">Refresh to try again</div>
            <br/>
            <div><b>Total: ${segmentValue}</b></div>
          </div>
        `;
        }

        if (cached && cached !== 'loading' && cached !== 'error') {
          const rows = cached
            .filter((r) => !!r.cost)
            .map((r) => {
              const valueStr = costFormatter({ cent: r.cost });

              return `
            <tr>
              <td style="padding-right:8px;">\u25CF ${r.routeName}</td>
              <td style="text-align:right;">${valueStr}</td>
            </tr>
          `;
            }).join('');

          const routeTotal = cached.reduce((sum, r) => sum + r.cost, 0);
          const totalStr = costFormatter({ cent: routeTotal });

          return `
          <div>
            <div>${dateStr}</div>
            <br/>
            <div>${params.marker}${params.seriesName}</div>
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
        }

        return `
        <div>
          <div>${dateStr}</div>
          <br/>
          <div>${params.marker}${params.seriesName}: ${segmentValue}</div>
        </div>
      `;
      },
    },
  });
};
