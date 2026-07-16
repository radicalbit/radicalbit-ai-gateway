import Lucide from '@Components/lucide';
import useModals, { modals } from '@Hooks/use-modals';
import Logo from '@Img/logo.png';
import { PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import { useGetRouteByNameWithRange } from '@Src/store/state/routes/vertical-hooks';
import {
  Board,
  Button, Collapse, DataTable,
  Skeleton,
  Void,
} from '@radicalbit/radicalbit-design-system';
import { Plus } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import columns from './columns';

function AssociatedGroups() {
  const { name } = useParams();
  const { data, isLoading, isSuccess, isError, refetch } = useGetRouteByNameWithRange(name);
  const groups = data?.groups || [];
  const count = groups.length;

  if (isLoading) {
    return <IsLoading />;
  }

  if (isError) {
    return <IsError refetch={refetch} />;
  }

  if (!isSuccess) {
    return false;
  }

  return (
    <Collapse
      key={`${name}-${count}`} // needed to re-render the collapse
      className="py-4"
      defaultActiveKey={['1']}
      items={[
        {
          key: '1',
          label: <Label />,
          children: <Children />,
        },
      ]}
      type="no-border"
    />
  );
}

function IsLoading() {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton.Input
        active
        className="flex-1"
        style={{
          height: 160,
          width: '100%',
          borderRadius: 8,
        }}
      />

      <Skeleton.Input
        active
        style={{
          height: 160,
          width: '100%',
          borderRadius: 8,
        }}
      />
    </div>
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
          image={<img alt="Logo" src={Logo} />}
          style={{ height: '80vh' }}
          title="Unable to load route"
        />
      )}
    />
  );
}

function Label() {
  const { showModal } = useModals();

  const { name } = useParams();
  const { data } = useGetRouteByNameWithRange(name);
  const groups = data?.groups || [];
  const count = groups.length;

  const handleOnClick = (e) => {
    e.stopPropagation();
    showModal(modals.ADD_GROUPS_TO_ROUTE, { name });
  };

  if (count === 1) {
    return (
      <div className="flex justify-between items-center">
        <strong>{`${count} Associated groups`}</strong>

        <Button icon={<Lucide icon={Plus} />} onClick={handleOnClick}>Associate groups</Button>
      </div>
    );
  }

  return (
    <div className="flex justify-between items-center">
      <strong>{`${count} Associated groups`}</strong>

      <Button icon={<Lucide icon={Plus} />} onClick={handleOnClick}>Associate groups</Button>
    </div>
  );
}

function Children() {
  const navigate = useNavigate();
  const { name } = useParams();
  const { data, isLoading } = useGetRouteByNameWithRange(name);
  const groups = data?.groups || [];

  const handleOnRowClick = (record) => {
    navigate(`/${PathsEnum.GROUPS}/${record.uuid}?${SEARCH_PARAMS.groups}=${encodeURIComponent(record.name)}`);
  };

  return (
    <DataTable
      clickable
      columns={columns}
      dataSource={groups}
      loading={isLoading}
      onRow={(record) => ({
        onClick: () => {
          handleOnRowClick(record);
        },
      })}
      pagination={{
        hideOnSinglePage: true,
      }}
      rowKey={({ uuid: routeUUID }) => routeUUID}
      size="small"
    />
  );
}

export default AssociatedGroups;
