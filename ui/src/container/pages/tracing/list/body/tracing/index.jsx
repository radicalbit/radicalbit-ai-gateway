import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import useModals, { modals } from '@Hooks/use-modals';
import { useGetTracesWithRange } from '@Src/store/state/tracing/vertical-hooks';
import { Board, DataTable, SectionTitle, Skeleton } from '@radicalbit/radicalbit-design-system';
import { useSearchParams } from 'react-router-dom';
import columns from './columns';

function Tracing() {
  const { showModal } = useModals();
  const [searchParams, setSearchParams] = useSearchParams();
  const currentPage = Number(searchParams.get('tracing-table-page')) || 1;

  const { data, isError, isLoading, isSuccess } = useGetTracesWithRange({ page: currentPage });
  const items = data?.items || [];

  const handleTableChange = (pagination) => {
    setSearchParams((prev) => {
      prev.set('tracing-table-page', pagination.current);
      return prev;
    });
  };

  const handleOnRowClick = (record) => {
    showModal(modals.TRACE_DETAIL, { traceId: record.traceId });
  };

  if (isLoading) {
    return (
      <Board
        header={<SectionTitle title="Traces" />}
        main={<Skeleton active block />}
      />
    );
  }

  if (isError) {
    return (
      <Board
        header={<SectionTitle title="Traces" />}
        main={<SomethingWentWrong size="small" />}
      />
    );
  }

  if (!isSuccess) {
    return null;
  }

  if (items.length === 0) {
    return (
      <Board
        header={<SectionTitle title="Traces" />}
        main={(
          <DataTable
            clickable
            columns={columns}
            dataSource={[]}
            onChange={handleTableChange}
            onRow={(record) => ({
              onClick: () => { handleOnRowClick(record); },
            })}
            pagination={{
              current: data.page,
              pageSize: data.size,
              total: data.total,
            }}
          />
        )}
      />
    );
  }

  return (
    <Board
      header={<SectionTitle title="Traces" />}
      main={(
        <DataTable
          clickable
          columns={columns}
          dataSource={items}
          onChange={handleTableChange}
          onRow={(record) => ({
            onClick: () => { handleOnRowClick(record); },
          })}
          pagination={{
            current: data.page,
            pageSize: data.size,
            total: data.total,
          }}
          rowKey="traceId"
        />
      )}
    />
  );
}

export default Tracing;
