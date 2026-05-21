import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import { DEFAULT_POLLING_INTERVAL } from '@Src/constants';
import { useGetTokensForChartsByRouteNameWithRange } from '@Src/store/state/costs/vertical-hooks';
import { Board, Skeleton, Void } from '@radicalbit/radicalbit-design-system';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import { LineChart } from 'echarts/charts';
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
  LineChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
  CanvasRenderer,
  TitleComponent,
]);

const chartWidthAndHeight = {
  width: '100%',
  height: '12.5rem',
};

function TokensGraph({ routeName }) {
  const { data, isError, isLoading, isSuccess } = useGetTokensForChartsByRouteNameWithRange({ routeName });

  usePollingGetRouteTokens(routeName);

  if (isLoading) {
    return (<Skeleton.Input active block style={chartWidthAndHeight} />);
  }

  if (isError) {
    return (
      <Board
        main={<SomethingWentWrong size="xsmall" />}
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
              No tokens data available yet. Chart will appear automatically when some data arrived.
            </>
          )}
          size="small"
          style={chartWidthAndHeight}
          title="Tokens Analysis Overview"
        />
      )}
      size="xsmall"
    />
  );
}

function IsSuccess({ routeName }) {
  const chartRef = useRef(null);
  const { data } = useGetTokensForChartsByRouteNameWithRange({ routeName });
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

const usePollingGetRouteTokens = (routeName) => {
  const [pollingInterval, setPollingInterval] = useState(DEFAULT_POLLING_INTERVAL);
  const { isError } = useGetTokensForChartsByRouteNameWithRange({ routeName }, { pollingInterval });

  useEffect(() => {
    setPollingInterval(isError ? 0 : DEFAULT_POLLING_INTERVAL);
  }, [isError]);
};

export default TokensGraph;
