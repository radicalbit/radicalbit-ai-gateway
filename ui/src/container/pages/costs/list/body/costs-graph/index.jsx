import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import { DEFAULT_POLLING_INTERVAL } from '@Src/constants';
import { useGetCostsForChartsByRouteNameWithRange } from '@Src/store/state/costs/vertical-hooks';
import { Board, Skeleton, Void } from '@radicalbit/radicalbit-design-system';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import { BarChart } from 'echarts/charts';
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import useDarkModeChart, { updateTheme } from '@Hooks/use-chart-dark-mode';
import { COSTS_GROUP_BY } from '..';
import option from './option';

echarts.use([
  BarChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
  CanvasRenderer,
  TitleComponent,
]);

const chartWidthAndHeight = {
  width: '100%',
  height: '25rem',
};

function CostsGraph({ routeName }) {
  const { data: costs, isError, isLoading, isSuccess } = useGetCostsForChartsByRouteNameWithRange({ routeName });
  const data = costs?.data || [];

  usePollingGetRouteCosts(routeName);

  if (isLoading) {
    return (<Skeleton.Input active block style={chartWidthAndHeight} />);
  }

  if (isError) {
    return <IsError />;
  }

  if (!data.length) {
    return <IsEmpty />;
  }

  if (!isSuccess) {
    return null;
  }

  return <IsSuccess routeName={routeName} />;
}

function IsError() {
  return (
    <Board
      main={<SomethingWentWrong size="small" style={chartWidthAndHeight} />}
      size="xsmall"
    />
  );
}

function IsEmpty() {
  return (
    <Board
      main={(
        <Void
          description={(
            <>
              No cost data available yet. Chart will appear automatically when some data arrived.
            </>
          )}
          style={chartWidthAndHeight}
          title="Cost Analysis Overview"
        />
      )}
    />
  );
}

function IsSuccess({ routeName }) {
  const chartRef = useRef(null);
  const { data } = useGetCostsForChartsByRouteNameWithRange({ routeName });
  const keyRef = useGetChartKeyRef();

  // Let the key change in the exact same rendering of the series array, that will trigger
  // the full re-render of the chart
  const { series, key } = useMemo(() => (
    {
      series: (data.data || []).map(({ name, data: d }) => ({
        name,
        data: d || [],
      })),
      key: keyRef.current,
    }), [data.data, keyRef]);

  useDarkModeChart(chartRef, series);

  return (
    <ReactEChartsCore
      key={key}
      echarts={echarts}
      lazyUpdate
      notMerge={false}
      onChartReady={() => updateTheme(chartRef)}
      option={option({
        xAxisData: data.timestamp || [],
        series,
        granularity: data.granularity,
        total: data.total,
      })}
      ref={chartRef}
      style={{
        width: '100%',
        height: '25rem',
        borderRadius: 'var(--coo-border-radius-small)',
        overflow: 'hidden',
      }}
    />
  );
}

const useGetChartKeyRef = () => {
  const ref = useRef();

  const [searchParams] = useSearchParams();
  const gte = searchParams.get('gte') || null;
  const from = searchParams.get('from') || null;
  const to = searchParams.get('to') || null;
  const groupBy = searchParams.get('groupBy') || COSTS_GROUP_BY.groups.key;

  useEffect(() => {
    ref.current = [gte, from, to, groupBy].filter(Boolean).join('-');
  }, [from, groupBy, gte, to]);

  return ref;
};

const usePollingGetRouteCosts = (routeName) => {
  const [pollingInterval, setPollingInterval] = useState(DEFAULT_POLLING_INTERVAL);
  const { isError } = useGetCostsForChartsByRouteNameWithRange({ routeName }, { pollingInterval });

  useEffect(() => {
    setPollingInterval(isError ? 0 : DEFAULT_POLLING_INTERVAL);
  }, [isError]);
};

export default CostsGraph;
