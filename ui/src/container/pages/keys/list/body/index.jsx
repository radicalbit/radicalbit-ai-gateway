import { Popup, usePopup } from '@Components/popup';
import { MAIN_LAYOUT_CONFIGURATION } from '@Container/layout/layout-provider/layout-provider-configuration';
import { useGetThreeDotsMenuItems } from '@Container/pages/keys/three-dots-menu';
import useModals, { modals } from '@Hooks/use-modals';
import {
  useGetKeysQuery, useDeleteKeyMutation, useEditKeyMutation, useAddGroupToKeyMutation,
} from '@State/keys/api';
import { SEARCH_PARAMS } from '@Src/constants';
import {
  faCircleXmark, faInbox, faPlus, faWarning,
} from '@fortawesome/free-solid-svg-icons';
import {
  Board,
  Button,
  DataTable,
  FontAwesomeIcon,
  Search,
  Spin,
  Void,
} from '@radicalbit/radicalbit-design-system';
import { useEffect } from 'react';
import { useDispatch } from 'react-redux';
import { useParams, useSearchParams } from 'react-router-dom';
import columns from './columns';

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
      <div className="flex flex-row items-center gap-4 pt-4">
        <Search
          allowClear={{ clearIcon: <FontAwesomeIcon icon={faCircleXmark} /> }}
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
  const { data = [], isSuccess } = useGetKeysQuery();
  const filteredData = searchValue
    ? data.filter(({ name }) => name.toLowerCase().includes(searchValue.toLowerCase()))
    : data;
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
  useInitLayoutConfigurations();

  const { data = [], isError, isLoading, isSuccess, refetch } = useGetKeysQuery();

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

  if (data.length === 0) {
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
      {/* IF scroll={{ y: 'calc(100vh - 10rem)' }} is defined, colSpan must be === columns.length */}
      <td colSpan={7}>
        <Spin spinning />
      </td>
    </tr>
  ) : (
    <tr {...other}>{children}</tr>
  );
}

function IsSuccess({ searchValue }) {
  const { popup, openPopup, closePopup } = usePopup();
  const items = useGetThreeDotsMenuItems(popup?.record?.uuid);

  const { uuid } = useParams();

  const { data = [] } = useGetKeysQuery();

  const filteredData = searchValue
    ? data.filter(({ name }) => name.toLowerCase().includes(searchValue.toLowerCase()))
    : data;

  const components = { body: { row: RowWithSpinner } };

  return (
    <>
      <DataTable
        columns={columns}
        components={components}
        dataSource={filteredData}
        onRow={(record) => ({
          onContextMenu: (event) => {
            openPopup(event, record);
          },
        })}
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

    </>
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
          actions={<Button onClick={handleOnClick} prefix={<FontAwesomeIcon icon={faPlus} />} type="primary">Create credential</Button>}
          description={(
            <>
              Looks like you have to create your first credential.
              <br />
              Please note that we do not display your credentials again after you generate them.
            </>
          )}
          image={<FontAwesomeIcon icon={faInbox} />}
          title="Credentials"
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
          image={<FontAwesomeIcon icon={faWarning} />}
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
