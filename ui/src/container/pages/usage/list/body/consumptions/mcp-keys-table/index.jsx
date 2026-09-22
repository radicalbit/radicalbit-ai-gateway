import Lucide from '@Components/lucide';
import { useGetMcpKeyUsageWithRange } from '@State/usage/vertical-hooks';
import {
  Board, Button, DataTable, SectionTitle, Skeleton, Void,
} from '@radicalbit/radicalbit-design-system';
import { TriangleAlert } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import columns from './columns';

const PAGE_SEARCH_PARAM = 'mcpKeysTablePage';

const tableHeight = { height: '20rem', width: '100%' };

const BOARD_TITLE = 'MCP Key Usage';

const useMcpKeyUsage = () => {
  const [searchParams] = useSearchParams();
  const page = Number(searchParams.get(PAGE_SEARCH_PARAM)) || 1;
  const routes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];

  return useGetMcpKeyUsageWithRange({ routes, page });
};

function McpKeysTable() {
  const {
    data, isError, isLoading, isFetching, isSuccess, refetch,
  } = useMcpKeyUsage();

  if (isLoading) {
    return <IsLoading />;
  }

  if (isError) {
    return <IsError isFetching={isFetching} refetch={refetch} />;
  }

  if (!data?.total) {
    return <IsEmpty />;
  }

  if (!isSuccess) {
    return false;
  }

  return <IsSuccess data={data} />;
}

function IsLoading() {
  return (
    <Board
      header={<SectionTitle modifier="pl-4" size="medium" title={BOARD_TITLE} />}
      main={<Skeleton.Node active style={tableHeight} />}
    />
  );
}

function IsError({ isFetching, refetch }) {
  return (
    <Board
      header={<SectionTitle modifier="pl-4" size="medium" title={BOARD_TITLE} />}
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
          style={tableHeight}
          title="Unable to load MCP key usage"
        />
      )}
    />
  );
}

function IsEmpty() {
  return (
    <Board
      header={<SectionTitle modifier="pl-4" size="medium" title={BOARD_TITLE} />}
      main={(
        <Void
          description="No MCP key usage data available yet. Table will appear automatically when some data arrived."
          style={tableHeight}
          title="MCP Key Usage Overview"
        />
      )}
    />
  );
}

function IsSuccess({ data }) {
  const [, setSearchParams] = useSearchParams();

  const handleOnTableChange = (pagination) => {
    setSearchParams((prev) => {
      prev.set(PAGE_SEARCH_PARAM, pagination.current);
      return prev;
    });
  };

  return (
    <Board
      header={<SectionTitle modifier="pl-4" size="medium" title={BOARD_TITLE} />}
      main={(
        <DataTable
          columns={columns}
          dataSource={data.items}
          onChange={handleOnTableChange}
          pagination={{
            current: data.page,
            pageSize: data.size,
            total: data.total,
          }}
          rowKey="keyUuid"
          size="small"
        />
      )}
    />
  );
}

export default McpKeysTable;
