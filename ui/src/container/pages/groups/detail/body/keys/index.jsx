import Lucide from '@Components/lucide';
import useModals, { modals } from '@Hooks/use-modals';
import { useGetGroupQuery } from '@State/groups/api';
import {
  Button, Collapse, DataTable, Spinner, Tooltip,
} from '@radicalbit/radicalbit-design-system';
import { Plus } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { GATEWAY_OWNER, PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import columns from './columns';

function Keys() {
  const { uuid } = useParams();
  const { data } = useGetGroupQuery(uuid);
  const keys = data?.routes || [];
  const count = keys.length;

  return (
    <Collapse
      key={`key-${uuid}-${count}`} // needed to re-render the collapse
      defaultActiveKey={['1']}
      items={[
        {
          key: '1',
          label: <LabelKey />,
          children: <ChildrenKey />,
        },
      ]}
      type="no-border"
    />
  );
}

const DISABLED_GROUP_TOOLTIP = 'This group is managed externally and cannot be modified';

function LabelKey() {
  const { showModal } = useModals();

  const { uuid } = useParams();
  const { data, isLoading, isError, isSuccess } = useGetGroupQuery(uuid);
  const keys = data?.keys || [];
  const count = keys.length;
  const owner = data?.owner;
  const isExternallyManaged = owner !== GATEWAY_OWNER;

  const handleOnClick = (e) => {
    e.stopPropagation();
    showModal(modals.ADD_KEYS_TO_GROUP, { uuid });
  };

  if (isLoading) {
    return <Spinner />;
  }

  if (!isSuccess || isError) {
    return false;
  }

  const label = count === 1 ? `${count} Associated credential` : `${count} Associated credentials`;

  const associateButton = isExternallyManaged
    ? (
      <Tooltip title={DISABLED_GROUP_TOOLTIP}>
        <span>
          <Button disabled icon={<Lucide icon={Plus} />}>Associate credentials</Button>
        </span>
      </Tooltip>
    )
    : <Button icon={<Lucide icon={Plus} />} onClick={handleOnClick}>Associate credentials</Button>;

  return (
    <div className="flex justify-between items-center">
      <strong>{label}</strong>

      {associateButton}
    </div>
  );
}

function ChildrenKey() {
  const navigate = useNavigate();
  const { uuid } = useParams();
  const { data, isLoading } = useGetGroupQuery(uuid);
  const keys = data?.keys || [];

  const handleOnRowClick = (record) => {
    navigate(`/${PathsEnum.CREDENTIALS}?${SEARCH_PARAMS.credentials}=${encodeURIComponent(record.name)}`);
  };

  return (
    <DataTable
      clickable
      columns={columns}
      dataSource={keys}
      loading={isLoading}
      onRow={(record) => ({
        onClick: () => {
          handleOnRowClick(record);
        },
      })}
      pagination={{
        hideOnSinglePage: true,
      }}
      rowKey={({ uuid: keyUUID }) => keyUUID}
      size="small"
    />
  );
}

export default Keys;
