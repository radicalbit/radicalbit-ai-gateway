import Lucide from '@Components/lucide';
import SuccessMessage from '@Components/success-message';
import { DATE_FORMAT } from '@Src/constants';
import { useRemoveRouteFromGroupMutation } from '@State/groups/api';
import {
  DataTableAction,
  Popconfirm, RelativeDateTime, SectionTitle, TextWithBold, Tooltip, Truncate,
} from '@radicalbit/radicalbit-design-system';
import { Trash2 } from 'lucide-react';
import { useParams, useSearchParams } from 'react-router-dom';

const columns = [
  {
    title: 'Name',
    dataIndex: 'name',
    key: 'name',
    render: (value) => (
      <Truncate tooltip={{ title: value, placement: 'topLeft' }}>
        <span className="font-[var(--coo-font-weight-bold)]">{value}</span>
      </Truncate>
    ),
  },
  {
    title: 'Created',
    dataIndex: 'createdAt',
    key: 'createdAt',
    align: 'right',
    render: (date) => <RelativeDateTime format={DATE_FORMAT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
  },
  {
    title: 'Updated',
    dataIndex: 'updatedAt',
    key: 'updatedAt',
    align: 'right',
    render: (date) => <RelativeDateTime format={DATE_FORMAT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
  },
  {
    title: '',
    dataIndex: 'groups',
    key: 'actions',
    render: (name, record) => <DataTableAction><Actions name={name} record={record} /></DataTableAction>,
  },
];

function Actions({ record: { uuid } }) {
  const { name } = useParams();
  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');
  const [trigger] = useRemoveRouteFromGroupMutation({ fixedCacheKey: `remove-route-${name}-from-group-${uuid}` });

  const handleOnDelete = async () => {
    const { error } = await trigger({
      uuid,
      projectUuid,
      routeName: name,
      successMessage: <SuccessMessage prefix="Group" strong={name} suffix="removed" />,
    });

    if (error) {
      console.error(error);
    }
  };

  const handleOnCancel = (e) => { e.stopPropagation(); };

  return (
    <div className="flex gap-4">
      <Tooltip title="Remove">
        <Popconfirm
          cancelButtonProps={{ type: 'secondary-light' }}
          description={<TextWithBold bold={name} isQuestion text="Are you sure you want to remove from the route the group" />}
          label={<Lucide icon={Trash2} />}
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
