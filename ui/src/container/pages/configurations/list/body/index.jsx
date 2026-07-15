import { WIDE_MAIN_LAYOUT_CONFIGURATION } from '@Container/layout/layout-provider/layout-provider-configuration';
import useModals, { modals } from '@Hooks/use-modals';
import { ConfigListFilterEnum, SEARCH_PARAMS } from '@Src/constants';
import { useGetAllConfigurationsQuery } from '@State/projects/api';
import { faCircleXmark, faInbox, faWarning } from '@fortawesome/free-solid-svg-icons';
import {
  Board,
  Button,
  DataTable,
  FontAwesomeIcon,
  Search,
  Void,
} from '@radicalbit/radicalbit-design-system';
import { useEffect, useMemo } from 'react';
import { useDispatch } from 'react-redux';
import { useSearchParams } from 'react-router-dom';
import getColumns from './columns';
import StatusTabs, { STATUS_QP } from './status-tabs';

function ConfigurationsList() {
  const [searchParams, setSearchParams] = useSearchParams();
  const searchValue = searchParams.get(SEARCH_PARAMS.configurations) || '';

  const handleSearchChange = (e) => {
    const { value } = e.target;
    setSearchParams((prev) => {
      if (value) {
        prev.set(SEARCH_PARAMS.configurations, value);
      } else {
        prev.delete(SEARCH_PARAMS.configurations);
      }
      return prev;
    });
  };

  return (
    <div className="flex flex-col gap-4 h-full">
      <div className="flex flex-row items-center gap-4">
        <Search
          allowClear={{ clearIcon: <FontAwesomeIcon icon={faCircleXmark} /> }}
          onChange={handleSearchChange}
          placeholder="Search by project name"
          style={{ width: '300px' }}
          value={searchValue}
        />

        <StatusTabs />
      </div>

      <ConfigurationsTable searchValue={searchValue} />
    </div>
  );
}

function ConfigurationsTable({ searchValue }) {
  useInitLayoutConfigurations();

  const [searchParams] = useSearchParams();
  const status = searchParams.get(STATUS_QP) || ConfigListFilterEnum.ALL;

  const {
    data = [], isError, isLoading, isFetching, isSuccess, refetch,
  } = useGetAllConfigurationsQuery({ status });

  if (isLoading) {
    return <DataTable loading />;
  }

  if (isError) {
    return <IsError isFetching={isFetching} refetch={refetch} />;
  }

  if (!data?.length) {
    return <IsEmpty />;
  }

  if (!isSuccess) {
    return false;
  }

  return <IsSuccess searchValue={searchValue} status={status} />;
}

function IsSuccess({ searchValue, status }) {
  const { showModal } = useModals();
  const { data = [] } = useGetAllConfigurationsQuery({ status });

  const filteredData = searchValue
    ? data.filter(({ name }) => name.toLowerCase().includes(searchValue.toLowerCase()))
    : data;

  const sortedData = useMemo(
    () => [...filteredData].sort((a, b) => (b.createdAt ?? '').localeCompare(a.createdAt ?? '')),
    [filteredData],
  );

  const columns = getColumns();

  const handleOnRowClick = (record) => {
    showModal(modals.EDIT_PROJECT_CONFIG, { uuid: record.uuid });
  };

  return (
    <DataTable
      clickable
      columns={columns}
      dataSource={sortedData}
      onRow={(record) => ({
        onClick: () => {
          handleOnRowClick(record);
        },
      })}
      pagination={{ hideOnSinglePage: true }}
      rowKey={({ uuid }) => uuid}
      scroll={{ y: 'calc(100vh - 10rem)' }}
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
            image={<FontAwesomeIcon icon={faWarning} />}
            title="Unable to load configurations"
          />
        )}
        width="100%"
      />
    </div>
  );
}

function IsEmpty() {
  return (
    <div className="flex justify-center h-full">
      <Board
        main={(
          <Void
            description="No configurations found."
            image={<FontAwesomeIcon icon={faInbox} />}
            title="Configurations"
          />
        )}
        width="100%"
      />
    </div>
  );
}

const useInitLayoutConfigurations = () => {
  const dispatch = useDispatch();

  useEffect(() => {
    WIDE_MAIN_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
  }, [dispatch]);
};

export default ConfigurationsList;
