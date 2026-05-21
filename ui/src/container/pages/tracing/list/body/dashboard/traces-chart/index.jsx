import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import useDarkModeChart, { updateTheme } from '@Hooks/use-chart-dark-mode';
import { useGetTracesChartWithRange } from '@Src/store/state/tracing/vertical-hooks';
import { Board, Skeleton, Void } from '@radicalbit/radicalbit-design-system';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import { useEffect, useMemo, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { echarts, tracesBarChartOption } from './options';

const chartWidthAndHeight = {
  width: '100%',
  height: '25rem',
};

function TracesChart() {
  const { data, isError, isLoading, isSuccess } = useGetTracesChartWithRange();
  const chartData = data?.data || [];

  if (isLoading) {
    return <Skeleton.Input active block style={chartWidthAndHeight} />;
  }

  if (isError) {
    return (
      <Board
        main={<SomethingWentWrong size="small" style={chartWidthAndHeight} />}
        size="xsmall"
      />
    );
  }

  if (!chartData.length) {
    return <TracesChartEmpty />;
  }

  if (!isSuccess) {
    return null;
  }

  return <TracesChartSuccess />;
}

function TracesChartEmpty() {
  return (
    <Board
      main={(
        <Void
          description="No trace data available yet. Chart will appear automatically when data arrives."
          style={chartWidthAndHeight}
          title="Traces by time"
        />
      )}
    />
  );
}

function TracesChartSuccess() {
  const chartRef = useRef(null);
  const { data } = useGetTracesChartWithRange();
  const keyRef = useGetChartKeyRef();

  const { series, key } = useMemo(() => ({
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
      option={tracesBarChartOption({
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
  const from = searchParams.get('from') || null;
  const to = searchParams.get('to') || null;
  const routes = searchParams.get('routes') || null;

  useEffect(() => {
    ref.current = [from, to, routes].filter(Boolean).join('-');
  }, [from, routes, to]);

  return ref;
};

export default TracesChart;
