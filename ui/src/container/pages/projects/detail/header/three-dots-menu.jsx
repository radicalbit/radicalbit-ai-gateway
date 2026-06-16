import SuccessMessage from '@Components/success-message';
import DeleteProject from '@Container/pages/projects/list/delete-project';
import useModals, { modals } from '@Hooks/use-modals';
import { ConfigStatusEnum } from '@Src/constants';
import {
  useApproveConfigMutation,
  useCancelApprovalMutation,
  useGetProjectQuery,
  useServeConfigMutation,
  useUnserveConfigMutation,
} from '@State/projects/api';
import {
  faCircleStop,
  faCodePullRequest,
  faEllipsisVertical,
  faPenToSquare,
  faPlay,
  faStop,
  faTrash,
} from '@fortawesome/free-solid-svg-icons';
import {
  Button, Dropdown, FontAwesomeIcon,
} from '@radicalbit/radicalbit-design-system';
import { useParams } from 'react-router-dom';

function ThreeDotsMenu() {
  const { uuid } = useParams();
  const items = useGetThreeDotsMenuItems(uuid);

  if (!uuid) {
    return false;
  }

  return (
    <Dropdown className="c-project-config-menu" menu={{ items }}>
      <Button type="text">
        <FontAwesomeIcon icon={faEllipsisVertical} />
      </Button>
    </Dropdown>
  );
}

export const useGetThreeDotsMenuItems = (uuid) => {
  const { data, isLoading, isError, isSuccess } = useGetProjectQuery(uuid, { skip: !uuid });

  const configs = data?.configs ?? [];

  const editConfigItem = useEditConfigItem(uuid);
  const configAMenu = useConfigSubmenu(uuid, configs[0]);
  const configBMenu = useConfigSubmenu(uuid, configs[1]);
  const deleteProjectItems = useDeleteProjectItems(uuid);

  if (!uuid) {
    return [];
  }

  if (isLoading || !isSuccess || isError || !data) {
    return [];
  }

  const slotGroups = [configAMenu, configBMenu].filter(Boolean);

  const slotsDivider = editConfigItem && slotGroups.length
    ? { type: 'divider', key: 'slots-divider' }
    : false;

  const configurationItems = [
    editConfigItem,
    slotsDivider,
    ...slotGroups,
  ].filter(Boolean);

  return [
    ...configurationItems,
    ...deleteProjectItems,
  ].filter(Boolean);
};

const useEditConfigItem = (uuid) => {
  const { showModal } = useModals();

  const handleOnClick = () => {
    showModal(modals.EDIT_PROJECT_CONFIG, { uuid });
  };

  return {
    key: 'edit-configuration',
    icon: <FontAwesomeIcon icon={faPenToSquare} />,
    label: 'Edit Configuration',
    onClick: handleOnClick,
  };
};

const useConfigSubmenu = (uuid, config) => {
  const { data: project } = useGetProjectQuery(uuid, { skip: !uuid });

  const configUuid = config?.uuid;
  const projectName = project?.name ?? '';

  const [triggerApprove, approveArgs] = useApproveConfigMutation({ fixedCacheKey: `approve-config-${configUuid}` });
  const [triggerCancel, cancelArgs] = useCancelApprovalMutation({ fixedCacheKey: `cancel-approval-${configUuid}` });
  const [triggerServe, serveArgs] = useServeConfigMutation({ fixedCacheKey: `serve-config-${configUuid}` });
  const [triggerUnserve, unserveArgs] = useUnserveConfigMutation({ fixedCacheKey: `unserve-config-${configUuid}` });

  const handleOnApprove = async () => {
    if (approveArgs.isLoading) {
      return;
    }

    await triggerApprove({
      projectUuid: uuid,
      configUuid,
      successMessage: <SuccessMessage prefix="Configuration for" strong={projectName} suffix="sent for publish" />,
    });
  };

  const handleOnCancel = async () => {
    if (cancelArgs.isLoading) {
      return;
    }

    await triggerCancel({
      projectUuid: uuid,
      configUuid,
      successMessage: <SuccessMessage prefix="Publish request for" strong={projectName} suffix="cancelled" />,
    });
  };

  const handleOnServe = async () => {
    if (serveArgs.isLoading) {
      return;
    }

    await triggerServe({
      projectUuid: uuid,
      configUuid,
      successMessage: <SuccessMessage prefix="Configuration for" strong={projectName} suffix="served" />,
    });
  };

  const handleOnUnserve = async () => {
    if (unserveArgs.isLoading) {
      return;
    }

    await triggerUnserve({
      projectUuid: uuid,
      configUuid,
      successMessage: <SuccessMessage prefix="Configuration for" strong={projectName} suffix="unserved" />,
    });
  };

  if (!config) {
    return false;
  }

  const children = [];

  if (config.configStatus === ConfigStatusEnum.DRAFT && config.configFile) {
    children.push({
      key: `approve-config-${configUuid}`,
      icon: <FontAwesomeIcon icon={faCodePullRequest} />,
      label: 'Request to Publish',
      onClick: handleOnApprove,
    });
  }

  if (config.configStatus === ConfigStatusEnum.READY_TO_SERVE) {
    children.push({
      key: `cancel-approval-${configUuid}`,
      icon: <FontAwesomeIcon icon={faCircleStop} />,
      label: 'Cancel Publish Request',
      onClick: handleOnCancel,
    });

    children.push({
      key: `serve-config-${configUuid}`,
      icon: <FontAwesomeIcon icon={faPlay} />,
      label: 'Publish',
      onClick: handleOnServe,
    });
  }

  if (config.configStatus === ConfigStatusEnum.SERVED) {
    children.push({
      key: `unserve-config-${configUuid}`,
      icon: <FontAwesomeIcon icon={faStop} />,
      label: 'Unpublish',
      onClick: handleOnUnserve,
    });
  }

  if (children.length === 0) {
    return false;
  }

  return {
    key: `config-${configUuid}`,
    type: 'group',
    label: `Slot ${config.slot}`,
    children,
  };
};

const useDeleteProjectItems = (uuid) => [
  { type: 'divider', key: 'configuration-divider' },
  {
    key: 'delete-project',
    label: (
      <DeleteProject uuid={uuid}>
        <div className="is-error flex items-center gap-2">
          <FontAwesomeIcon icon={faTrash} />

          Delete project
        </div>
      </DeleteProject>
    ),
  }];

export default ThreeDotsMenu;
