import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import { useGetInvocationsChartStreamWithRange } from '@State/usage/vertical-hooks';
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
import { useMemo, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
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
  height: '12.5rem',
};

function InvocationsGraph() {
  const [searchParams] = useSearchParams();
  const routes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];

  const { data, isError, isLoading, isSuccess } = useGetInvocationsChartStreamWithRange({ routes });

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

  if (!data?.data?.length) {
    return <IsEmpty />;
  }

  if (!isSuccess) {
    return null;
  }

  return <IsSuccess />;
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

function IsSuccess() {
  const [searchParams] = useSearchParams();
  const routes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];

  const chartRef = useRef(null);
  const { data } = useGetInvocationsChartStreamWithRange({ routes });
  const total = data?.total;

  const series = useMemo(() => [{ name: 'Invocations', data: data.data }], [data.data]);

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

export default InvocationsGraph;
