import Lucide from '@Components/lucide';
import { MAIN_LAYOUT_CONFIGURATION } from '@Container/layout/layout-provider/layout-provider-configuration';
import { useGetSecretsQuery } from '@State/secrets/api';
import {
  Board,
  Button,
  DataTable,
  Void,
} from '@radicalbit/radicalbit-design-system';
import { Inbox, TriangleAlert } from 'lucide-react';
import { useEffect } from 'react';
import { useDispatch } from 'react-redux';
import { useSearchParams } from 'react-router-dom';
import columns from './columns';

const PAGE_SEARCH_PARAM = 'secrets-table-page';
const SIZE_SEARCH_PARAM = 'secrets-table-size';

const readPaginationParams = (searchParams) => ({
  page: Number(searchParams.get(PAGE_SEARCH_PARAM)) || 1,
  limit: Number(searchParams.get(SIZE_SEARCH_PARAM)) || undefined,
});

function SecretsList() {
  const [searchParams, setSearchParams] = useSearchParams();
  const paginationParams = readPaginationParams(searchParams);

  const { data, isError, isLoading, isSuccess } = useGetSecretsQuery(paginationParams);
  const items = data?.items || [];
  const page = data?.page;
  const size = data?.size;
  const total = data?.total;

  const handleOnTableChange = (pagination) => {
    const current = pagination?.current;
    const pageSize = pagination?.pageSize;

    setSearchParams((prev) => {
      prev.set(PAGE_SEARCH_PARAM, current);
      prev.set(SIZE_SEARCH_PARAM, pageSize);
      return prev;
    });
  };

  useInitLayoutConfigurations();

  if (isLoading) {
    return <DataTable loading />;
  }

  if (isError) {
    return (
      <div className="flex justify-center h-full">
        <IsError />
      </div>
    );
  }

  if (!items.length) {
    return (
      <div className="flex justify-center h-full">
        <IsEmpty />
      </div>
    );
  }

  if (!isSuccess) {
    return false;
  }

  return (
    <DataTable
      columns={columns}
      dataSource={items}
      onChange={handleOnTableChange}
      pagination={{
        current: page,
        pageSize: size,
        total,
      }}
      rowKey="key"
      scroll={{ y: 'calc(100vh - 10rem)' }}
    />
  );
}

function IsEmpty() {
  return (
    <Board
      main={(
        <Void
          description="No secret key is available from the secrets backend."
          image={<Lucide icon={Inbox} />}
          title="Secrets"
        />
      )}
      width="100%"
    />
  );
}

function IsError() {
  const [searchParams] = useSearchParams();
  const paginationParams = readPaginationParams(searchParams);

  const { isFetching, refetch } = useGetSecretsQuery(paginationParams);

  const handleOnRetry = () => {
    refetch();
  };

  return (
    <Board
      main={(
        <Void
          actions={<Button loading={isFetching} onClick={handleOnRetry}>Retry</Button>}
          description={(
            <>
              This might be temporary
              <br />
              please retry later
            </>
          )}
          image={<Lucide icon={TriangleAlert} />}
          title="Unable to load secrets"
        />
      )}
      width="100%"
    />
  );
}

const useInitLayoutConfigurations = () => {
  const dispatch = useDispatch();

  useEffect(() => {
    MAIN_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
  }, [dispatch]);
};

export default SecretsList;
