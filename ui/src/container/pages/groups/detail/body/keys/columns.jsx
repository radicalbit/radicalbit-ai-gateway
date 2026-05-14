import SuccessMessage from '@Components/success-message';
import { DATE_FORMAT, GATEWAY_OWNER } from '@Src/constants';
import { useGetGroupQuery, useRemoveKeyFromGroupMutation } from '@State/groups/api';
import { faTrash } from '@fortawesome/free-solid-svg-icons';
import {
  DataTableAction,
  FontAwesomeIcon, Popconfirm, RelativeDateTime, SectionTitle, Skeleton, TextWithBold,
  Tooltip,
  Truncate,
} from '@radicalbit/radicalbit-design-system';
import { useParams } from 'react-router-dom';

const columns = [
  {
    title: 'Name',
    dataIndex: 'name',
    width: '40%',
    key: 'id',
    render: (value) => (
      <Truncate tooltip={{ title: value, placement: 'topLeft' }}>
        <span className="font-[var(--coo-font-weight-bold)]">{value}</span>
      </Truncate>
    ),
  },
  {
    title: 'Created',
    dataIndex: 'createdAt',
    align: 'right',
    width: '15%',
    render: (date) => <RelativeDateTime format={DATE_FORMAT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
  },
  {
    title: 'Updated',
    dataIndex: 'updatedAt',
    align: 'right',
    width: '15%',
    render: (date) => <RelativeDateTime format={DATE_FORMAT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
  },
  {
    title: '',
    dataIndex: 'uuid',
    align: 'uuid',
    width: '10%',
    render: (uuid, record) => <DataTableAction><Actions record={record} uuid={uuid} /></DataTableAction>,
  },
];

const DISABLED_GROUP_TOOLTIP = 'This group is managed externally and cannot be modified';

function Actions({ uuid: keyUUID, record: { name } }) {
  const { uuid } = useParams();
  const { data: groupData, isLoading, isError, isSuccess } = useGetGroupQuery(uuid);
  const isExternallyManaged = groupData?.owner !== GATEWAY_OWNER;

  const [trigger] = useRemoveKeyFromGroupMutation({ fixedCacheKey: `remove-key-${keyUUID}-from-group-${uuid}` });

  const handleOnDelete = async () => {
    const { error } = await trigger({
      uuid,
      keyUUID,
      successMessage: <SuccessMessage prefix="Group" strong={name} suffix="removed" />,
    });

    if (error) {
      console.error(error);
    }
  };

  const handleOnCancel = (e) => { e.stopPropagation(); };

  if (isLoading) {
    return <Skeleton.Avatar active shape="square" size="small" />;
  }

  if (!isSuccess || isError) {
    return false;
  }

  if (isExternallyManaged) {
    return (
      <div className="flex">
        <Tooltip title={DISABLED_GROUP_TOOLTIP}>
          <span>
            <FontAwesomeIcon disabled icon={faTrash} />
          </span>
        </Tooltip>
      </div>
    );
  }

  return (
    <div className="flex">
      <Tooltip title="Remove">
        <Popconfirm
          cancelButtonProps={{ type: 'secondary-light' }}
          description={<TextWithBold bold={name} isQuestion text="Are you sure you want to remove the group from the credential" />}
          label={<FontAwesomeIcon icon={faTrash} />}
          okText={<div className="is-error">Remove</div>}
          okType="error-light"
          onCancel={handleOnCancel}
          onConfirm={handleOnDelete}
          title={<SectionTitle size="small" title="Remove group" titleColor="error" />}
        />
      </Tooltip>
    </div>
  );
}

export default columns;
