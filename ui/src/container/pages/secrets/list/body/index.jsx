import Lucide from '@Components/lucide';
import { MAIN_LAYOUT_CONFIGURATION } from '@Container/layout/layout-provider/layout-provider-configuration';
import { SEARCH_PARAMS } from '@Src/constants';
import { useGetSecretsQuery } from '@State/secrets/api';
import {
  Board,
  Button,
  DataTable,
  Search,
  Void,
} from '@radicalbit/radicalbit-design-system';
import { CircleX, Inbox, TriangleAlert } from 'lucide-react';
import { useEffect } from 'react';
import { useDispatch } from 'react-redux';
import { useSearchParams } from 'react-router-dom';
import columns from './columns';

const PAGE_SEARCH_PARAM = 'secrets-table-page';
const SIZE_SEARCH_PARAM = 'secrets-table-size';

const readQueryParams = (searchParams) => ({
  page: Number(searchParams.get(PAGE_SEARCH_PARAM)) || 1,
  limit: Number(searchParams.get(SIZE_SEARCH_PARAM)) || undefined,
  search: searchParams.get(SEARCH_PARAMS.secrets) || undefined,
});

function SecretsList() {
  const [searchParams, setSearchParams] = useSearchParams();
  const searchValue = searchParams.get(SEARCH_PARAMS.secrets) || '';

  const handleOnSearchChange = (e) => {
    const value = e?.target?.value;

    setSearchParams((prev) => {
      if (value) {
        prev.set(SEARCH_PARAMS.secrets, value);
      } else {
        prev.delete(SEARCH_PARAMS.secrets);
      }
      prev.delete(PAGE_SEARCH_PARAM);
      return prev;
    });
  };

  useInitLayoutConfigurations();

  return (
    <div className="flex flex-col gap-4 h-full">
      <Search
        allowClear={{ clearIcon: <Lucide icon={CircleX} /> }}
        onChange={handleOnSearchChange}
        placeholder="Search secrets by key"
        style={{ width: '300px' }}
        value={searchValue}
      />

      <SecretsTable />
    </div>
  );
}

function SecretsTable() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryParams = readQueryParams(searchParams);

  const { data, isError, isFetching, isLoading, isSuccess } = useGetSecretsQuery(queryParams);
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
      loading={isFetching}
      onChange={handleOnTableChange}
      pagination={{
        current: page,
        pageSize: size,
        total,
      }}
      rowKey="key"
      scroll={{ y: 'calc(100vh - 13rem)' }}
    />
  );
}

function IsEmpty() {
  const [searchParams] = useSearchParams();
  const { search } = readQueryParams(searchParams);

  const description = search
    ? `No secret key matches "${search}".`
    : 'No secret key is available from the secrets backend.';

  return (
    <Board
      main={(
        <Void
          description={description}
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
  const queryParams = readQueryParams(searchParams);

  const { isFetching, refetch } = useGetSecretsQuery(queryParams);

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
