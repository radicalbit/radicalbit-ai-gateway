import Lucide from '@Components/lucide';
import useModals, { modals } from '@Hooks/use-modals';
import { useGetRequestsWithRange } from '@Src/store/state/tracing/vertical-hooks';
import {
  Board,
  Button,
  DataTable,
  SectionTitle,
  Skeleton,
  Void,
} from '@radicalbit/radicalbit-design-system';
import { TriangleAlert } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import columns from './columns';

function Tracing() {
  const { showModal } = useModals();
  const [searchParams, setSearchParams] = useSearchParams();
  const currentPage = Number(searchParams.get('tracing-table-page')) || 1;

  const {
    data, isError, isLoading, isFetching, isSuccess, refetch,
  } = useGetRequestsWithRange({ page: currentPage });
  const items = data?.items || [];

  const handleTableChange = (pagination) => {
    setSearchParams((prev) => {
      prev.set('tracing-table-page', pagination.current);
      return prev;
    });
  };

  // Until the request detail lands (AG-1109), a row opens its trace, if any.
  const handleOnRowClick = (record) => {
    if (record.traceId) {
      showModal(modals.TRACE_DETAIL, { traceId: record.traceId });
    }
  };

  if (isLoading) {
    return (
      <Board
        header={<SectionTitle title="Requests" />}
        main={<Skeleton active block />}
      />
    );
  }

  if (isError) {
    return <IsError isFetching={isFetching} refetch={refetch} />;
  }

  if (!isSuccess) {
    return null;
  }

  if (items.length === 0) {
    return (
      <Board
        header={<SectionTitle title="Requests" />}
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
      header={<SectionTitle title="Requests" />}
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
          rowKey="requestUuid"
        />
      )}
    />
  );
}

function IsError({ isFetching, refetch }) {
  return (
    <div className="flex justify-center h-full">
      <Board
        main={(
          <Void
            actions={<Button loading={isFetching} onClick={refetch}>Retry</Button>}
            description={(
              <>
                This might be temporary
                <br />
                please retry later
              </>
            )}
            image={<Lucide icon={TriangleAlert} />}
            title="Unable to load requests"
          />
        )}
        width="100%"
      />
    </div>
  );
}

export default Tracing;
