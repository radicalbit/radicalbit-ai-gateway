import { VisibleRowsProvider } from '@Components/limits/visible-rows-context';
import { Popup, usePopup } from '@Components/popup';
import Lucide from '@Components/lucide';
import { MAIN_LAYOUT_CONFIGURATION } from '@Container/layout/layout-provider/layout-provider-configuration';
import { useGetThreeDotsMenuItems } from '@Container/pages/keys/three-dots-menu';
import {
  OwnershipTabEnum, TAB_QP, filterByTab, parseTab,
} from '@Helpers/ownership-tabs';
import useModals, { modals } from '@Hooks/use-modals';
import {
  useGetKeysQuery, useDeleteKeyMutation, useEditKeyMutation, useAddGroupToKeyMutation,
} from '@State/keys/api';
import { SEARCH_PARAMS } from '@Src/constants';
import {
  Board,
  Button,
  DataTable,
  Search,
  Spin,
  Void,
} from '@radicalbit/radicalbit-design-system';
import { CircleX, Inbox, Plus, TriangleAlert } from 'lucide-react';
import { useEffect } from 'react';
import { useDispatch } from 'react-redux';
import { useParams, useSearchParams } from 'react-router-dom';
import columns from './columns';
import OwnershipTabs from './ownership-tabs';

function KeysList() {
  const [searchParams, setSearchParams] = useSearchParams();
  const searchValue = searchParams.get(SEARCH_PARAMS.credentials) || '';

  const handleSearchChange = (e) => {
    const { value } = e.target;
    setSearchParams((prev) => {
      if (value) {
        prev.set(SEARCH_PARAMS.credentials, value);
      } else {
        prev.delete(SEARCH_PARAMS.credentials);
      }
      return prev;
    });
  };

  return (
    <div className="flex flex-col gap-4 h-full">
      <OwnershipTabs />

      <div className="flex flex-row items-center gap-4">
        <Search
          allowClear={{ clearIcon: <Lucide icon={CircleX} /> }}
          aria-label="Search credentials by name"
          onChange={handleSearchChange}
          placeholder="Search credentials by name"
          style={{ width: '300px' }}
          value={searchValue}
        />

        <KeysCount searchValue={searchValue} />
      </div>

      <KeysTable searchValue={searchValue} />
    </div>
  );
}

function KeysCount({ searchValue }) {
  const [searchParams] = useSearchParams();

  const { data = [], isSuccess } = useGetKeysQuery();

  const tabData = filterByTab(data, parseTab(searchParams.get(TAB_QP)));
  const filteredData = searchValue
    ? tabData.filter(({ name }) => name.toLowerCase().includes(searchValue.toLowerCase()))
    : tabData;
  const count = filteredData.length;

  if (!isSuccess) {
    return false;
  }

  if (count === 1) {
    return (
      <div className="flex items-center">
        {`${count} Credential`}
      </div>
    );
  }

  return (
    <div className="flex items-center">
      {`${count} Credentials`}
    </div>
  );
}

function KeysTable({ searchValue }) {
  const [searchParams] = useSearchParams();

  const { data = [], isError, isLoading, isSuccess, refetch } = useGetKeysQuery();

  const tab = parseTab(searchParams.get(TAB_QP));
  const tabData = filterByTab(data, tab);

  useInitLayoutConfigurations();

  if (isLoading) {
    return <DataTable loading />;
  }

  if (isError) {
    return (
      <div className="flex justify-center h-full">
        <IsError refetch={refetch} />
      </div>
    );
  }

  if (!isSuccess) {
    return false;
  }

  if (tabData.length === 0 && tab === OwnershipTabEnum.EXTERNALLY_MANAGED) {
    return (
      <div className="flex justify-center h-full">
        <IsEmptyExternallyManaged />
      </div>
    );
  }

  if (tabData.length === 0) {
    return (
      <div className="flex justify-center h-full">
        <IsEmpty />
      </div>
    );
  }

  return (
    <IsSuccess searchValue={searchValue} />
  );
}

function RowWithSpinner({ children, ...other }) {
  const [, { isLoading: isEditing }] = useEditKeyMutation({ fixedCacheKey: `edit-key-${other['data-row-key']}` });
  const [, { isLoading: isDeleting }] = useDeleteKeyMutation({ fixedCacheKey: `delete-key-${other['data-row-key']}` });
  const [, { isLoading: isAddingGroups }] = useAddGroupToKeyMutation({ fixedCacheKey: `add-group-to-key-${other['data-row-key']}` });

  return (isEditing || isDeleting || isAddingGroups) ? (
    <tr {...other}>
      <td colSpan={columns.length}>
        <Spin spinning />
      </td>
    </tr>
  ) : (
    <tr {...other}>{children}</tr>
  );
}

function IsSuccess({ searchValue }) {
  // const { popup, openPopup, closePopup } = usePopup();
  const { popup, closePopup } = usePopup();
  const items = useGetThreeDotsMenuItems(popup?.record?.uuid);

  const { uuid } = useParams();
  const [searchParams] = useSearchParams();

  const { data = [] } = useGetKeysQuery();

  const tabData = filterByTab(data, parseTab(searchParams.get(TAB_QP)));
  const filteredData = searchValue
    ? tabData.filter(({ name }) => name.toLowerCase().includes(searchValue.toLowerCase()))
    : tabData;

  const components = { body: { row: RowWithSpinner } };

  return (
    <VisibleRowsProvider>
      <DataTable
        columns={columns}
        components={components}
        dataSource={filteredData}
        // FIXME: UI is broken
        // onRow={(record) => ({
        //   onContextMenu: (event) => {
        //     openPopup(event, record);
        //   },
        // })}
        pagination={{
          hideOnSinglePage: true,
        }}
        rowClassName={({ uuid: keyUUID }) => keyUUID === uuid ? DataTable.ROW_PRIMARY_LIGHT : undefined}
        rowKey={({ uuid: keyUUID }) => keyUUID}
        scroll={{ y: 'calc(100vh - 10rem)', x: '100vh' }}
      />

      <Popup
        items={items}
        onClose={closePopup}
        {...popup}
      />

    </VisibleRowsProvider>
  );
}

function IsEmpty() {
  const { showModal } = useModals();

  const handleOnClick = () => {
    showModal(modals.CREATE_KEY);
  };

  return (
    <Board
      main={(
        <Void
          actions={<Button onClick={handleOnClick} prefix={<Lucide icon={Plus} />} type="primary">Create credential</Button>}
          description={(
            <>
              Looks like you have to create your first credential.
              <br />
              Please note that we do not display your credentials again after you generate them.
            </>
          )}
          image={<Lucide icon={Inbox} />}
          title="Credentials"
        />
      )}
      width="100%"
    />
  );
}

function IsEmptyExternallyManaged() {
  return (
    <Board
      main={(
        <Void
          description="Credentials from your identity provider appear here after the sync"
          size="small"
          title="No externally managed credentials"
        />
      )}
      width="100%"
    />
  );
}

function IsError({ refetch }) {
  return (
    <Board
      main={(
        <Void
          actions={<Button onClick={refetch}>Retry</Button>}
          description={(
            <>
              This might be temporary
              <br />
              please retry later
            </>
          )}
          image={<Lucide icon={TriangleAlert} />}
          title="Unable to load credentials"
        />
      )}
      width="100%"
    />
  );
}

const useInitLayoutConfigurations = () => {
  const dispatch = useDispatch();
  const { uuid } = useParams();

  useEffect(() => {
    MAIN_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
  }, [dispatch, uuid]);
};

export default KeysList;
