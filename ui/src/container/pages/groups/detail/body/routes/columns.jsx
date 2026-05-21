import SuccessMessage from '@Components/success-message';
import { useRemoveRouteFromGroupMutation } from '@State/groups/api';
import { useGetProjectQuery } from '@State/projects/api';
import { faTrash } from '@fortawesome/free-solid-svg-icons';
import {
  DataTableAction, FontAwesomeIcon, Popconfirm,
  SectionTitle, Skeleton, TextWithBold, Tooltip, Truncate,
} from '@radicalbit/radicalbit-design-system';
import { useParams } from 'react-router-dom';

const columns = [
  {
    title: 'Name',
    dataIndex: 'name',
    key: 'name',
    width: '40%',
    render: (value) => (
      <Truncate tooltip={{ title: value, placement: 'topLeft' }}>
        <span className="font-[var(--coo-font-weight-bold)]">{value}</span>
      </Truncate>
    ),
  },
  {
    title: 'Project',
    dataIndex: 'projectUuid',
    key: 'projectUuid',
    width: '40%',
    render: (projectUuid) => <ProjectName projectUuid={projectUuid} />,
  },
  {
    title: '',
    dataIndex: 'name',
    key: 'actions',
    width: '10%',
    render: (name, record) => <DataTableAction><Actions name={name} record={record} /></DataTableAction>,
  },
];

function ProjectName({ projectUuid }) {
  const { data, isLoading, isError, isSuccess } = useGetProjectQuery(projectUuid, { skip: !projectUuid });

  if (isLoading) {
    return <Skeleton.Input active size="small" />;
  }

  if (isError) {
    return <span className="is-secondary">--</span>;
  }

  if (!isSuccess) {
    return false;
  }

  return (
    <Truncate tooltip={{ title: data?.name, placement: 'topLeft' }}>
      <span className="is-secondary">{data?.name}</span>
    </Truncate>
  );
}

function Actions({ name, record }) {
  const { uuid } = useParams();
  const projectUuid = record?.projectUuid;
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
    <div className="flex">
      <Tooltip title="Remove">
        <Popconfirm
          cancelButtonProps={{ type: 'secondary-light' }}
          description={<TextWithBold bold={name} isQuestion text="Are you sure you want to remove the group from the route" />}
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
