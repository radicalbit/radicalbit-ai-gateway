import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import { useGetSpanLatenciesWithRange } from '@Src/store/state/tracing/vertical-hooks';
import { Board, DataTable, SectionTitle, Skeleton, Void } from '@radicalbit/radicalbit-design-system';
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import columns from './columns';
import './index.less';

const EXPANDED_PARAM = 'expandedSpanCategories';

function SpanLatencies() {
  const { data, isError, isLoading, isSuccess } = useGetSpanLatenciesWithRange({ grouped: true });

  if (isLoading) {
    return (
      <Board
        header={<SectionTitle title="Span latencies" />}
        main={(
          <Skeleton active block />
        )}
      />
    );
  }

  if (isError) {
    return <IsError />;
  }

  if (!data?.data?.length) {
    return <IsEmpty />;
  }

  if (!isSuccess) {
    return null;
  }

  return <IsSuccess />;
}

function IsSuccess() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { data, isFetching } = useGetSpanLatenciesWithRange({ grouped: true });

  const expandedCategories = useMemo(() => {
    const param = searchParams.get(EXPANDED_PARAM);

    if (!param) {
      return new Set();
    }

    return new Set(param.split(','));
  }, [searchParams]);

  const spanLatencies = useMemo(() => {
    const items = data?.data || [];

    return items.flatMap(({ category, spans = [], ...percentiles }) => {
      const spanCount = spans.length;
      const headerPercentiles = isFetching ? {} : percentiles;
      const headerRow = { name: category, spanCount, ...headerPercentiles, header: true, key: `header:${category}` };

      if (!expandedCategories.has(category)) {
        return [headerRow];
      }

      const spanRows = (spans || []).map(({ spanName, ...spanPercentiles }) => ({
        name: spanName,
        ...(isFetching ? {} : spanPercentiles),
        header: false,
        key: `${category}:${spanName}`,
      }));

      return [headerRow, ...spanRows];
    });
  }, [data?.data, expandedCategories, isFetching]);

  const handleOnRow = (record) => {
    if (!record.header) {
      return {};
    }

    return {
      onClick: () => {
        setSearchParams((prev) => {
          const current = prev.get(EXPANDED_PARAM);
          const set = current ? new Set(current.split(',')) : new Set();

          if (set.has(record.name)) {
            set.delete(record.name);
          } else {
            set.add(record.name);
          }

          if (set.size === 0) {
            prev.delete(EXPANDED_PARAM);
          } else {
            prev.set(EXPANDED_PARAM, [...set].join(','));
          }

          return prev;
        });
      },
      style: { cursor: 'pointer' },
    };
  };

  return (
    <Board
      header={<SectionTitle title="Span latencies" />}
      main={(
        <DataTable
          columns={columns}
          dataSource={spanLatencies}
          onRow={handleOnRow}
          pagination={false}
          rowClassName={({ header }) => header ? undefined : DataTable.ROW_NOT_CLICKABLE}
          rowKey={(({ key }) => key)}
          sticky
        />
      )}
    />
  );
}

function IsError() {
  return (
    <Board
      header={<SectionTitle title="Span latencies" />}
      main={<SomethingWentWrong size="small" />}
    />
  );
}

function IsEmpty() {
  return (
    <Board
      header={<SectionTitle title="Span latencies" />}
      main={(
        <Void
          description="No span latency data available yet."
          title="Span latencies"
        />
      )}
    />
  );
}

export default SpanLatencies;
