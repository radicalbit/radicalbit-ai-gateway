import Lucide from '@Components/lucide';
import { SPAN_PARAM } from '@Components/modals/trace-detail/constants';
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
import RequestDetail from './request-detail';

// The open request lives in the URL, so a request detail can be linked to.
const REQUEST_PARAM = 'requestUuid';

function Tracing() {
  const [searchParams, setSearchParams] = useSearchParams();
  const currentPage = Number(searchParams.get('tracing-table-page')) || 1;
  const openRequestUuid = searchParams.get(REQUEST_PARAM);

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

  const expandedRowKeys = openRequestUuid ? [openRequestUuid] : [];

  // One request open at a time: the span selection (SPAN_PARAM) belongs to its trace.
  const handleOnExpand = (expanded, { requestUuid }) => {
    setSearchParams((prev) => {
      prev.delete(SPAN_PARAM);

      if (expanded) {
        prev.set(REQUEST_PARAM, requestUuid);
      } else {
        prev.delete(REQUEST_PARAM);
      }

      return prev;
    });
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
            columns={columns}
            dataSource={[]}
            onChange={handleTableChange}
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
          expandable={{
            expandedRowKeys,
            expandedRowRender,
            expandRowByClick: true,
            onExpand: handleOnExpand,
          }}
          onChange={handleTableChange}
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

function expandedRowRender({ requestUuid }) {
  return <RequestDetail requestUuid={requestUuid} />;
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
