import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import { DEFAULT_POLLING_INTERVAL } from '@Src/constants';
import { useGetInvocationsForChartsByRouteNameWithRange } from '@Src/store/state/costs/vertical-hooks';
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
import useDarkModeChart, { updateTheme } from '@Hooks/use-chart-dark-mode';
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

function InvocationsGraph({ routeName }) {
  const { data, isError, isLoading, isSuccess } = useGetInvocationsForChartsByRouteNameWithRange({ routeName, includeModels: true });

  usePollingGetRouteInvocations(routeName);

  if (isLoading) {
    return (<Skeleton.Input active block style={chartWidthAndHeight} />);
  }

  if (isError) {
    return (
      <Board
        main={<SomethingWentWrong size="small" style={chartWidthAndHeight} />}
        size="xsmall"
      />
    );
  }

  if (!data.data?.length) {
    return <IsEmpty />;
  }

  if (!isSuccess) {
    return null;
  }

  return <IsSuccess routeName={routeName} />;
}

function IsEmpty() {
  return (
    <Board
      main={(
        <Void
          description={(
            <>
              No invocations data available yet. Chart will appear automatically when some data arrived.
            </>
          )}
          size="small"
          style={chartWidthAndHeight}
          title="Models Invocations Overview"
        />
      )}
      size="xsmall"
    />
  );
}

function IsSuccess({ routeName }) {
  const chartRef = useRef(null);
  const { data } = useGetInvocationsForChartsByRouteNameWithRange({ routeName, includeModels: true });
  const total = data?.total;

  const series = useMemo(() => (data.data || []).map(({ name, data: d }) => ({
    name,
    data: d || [],
  })), [data.data]);

  useDarkModeChart(chartRef, series);

  return (
    <ReactEChartsCore
      echarts={echarts}
      lazyUpdate
      notMerge={false}
      onChartReady={() => updateTheme(chartRef)}
      option={option({
        xAxisData: data.timestamp || [],
        series,
        granularity: data.granularity,
        total,
      })}
      ref={chartRef}
      style={{
        ...chartWidthAndHeight,
        borderRadius: 'var(--coo-border-radius-small)',
        overflow: 'hidden',
      }}
    />
  );
}

const usePollingGetRouteInvocations = (routeName) => {
  const [pollingInterval, setPollingInterval] = useState(DEFAULT_POLLING_INTERVAL);
  const { isError } = useGetInvocationsForChartsByRouteNameWithRange({ routeName, includeModels: true }, { pollingInterval });

  useEffect(() => {
    setPollingInterval(isError ? 0 : DEFAULT_POLLING_INTERVAL);
  }, [isError]);
};

export default InvocationsGraph;
