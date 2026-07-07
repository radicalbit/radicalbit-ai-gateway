import SuccessMessage from '@Components/success-message';
import DeleteProject from '@Container/pages/projects/list/delete-project';
import useGetVisibleConfig from '@Container/pages/projects/use-get-visible-config';
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
  faPenToSquare,
  faPlay,
  faStop,
  faTrash,
} from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@radicalbit/radicalbit-design-system';

export const useGetThreeDotsMenuItems = (uuid) => {
  const { data, isLoading, isError, isSuccess } = useGetProjectQuery(uuid, { skip: !uuid });

  const configs = data?.configs ?? [];
  const visibleConfig = useGetVisibleConfig(configs);

  const editConfigItem = useEditConfigItem(uuid, visibleConfig);
  const visibleConfigActions = useVisibleConfigItems(uuid, visibleConfig);
  const deleteProjectItems = useDeleteProjectItems(uuid);

  if (!uuid) {
    return [];
  }

  if (isLoading || !isSuccess || isError || !data) {
    return [];
  }

  const configurationGroupItems = [editConfigItem, ...visibleConfigActions].filter(Boolean);

  const configurationGroup = configurationGroupItems.length
    ? {
      key: 'configuration-group',
      type: 'group',
      label: 'Configuration',
      children: configurationGroupItems,
    }
    : false;

  return [
    configurationGroup,
    ...deleteProjectItems,
  ].filter(Boolean);
};

const useEditConfigItem = (uuid, visibleConfig) => {
  const { showModal } = useModals();

  const handleOnClick = () => {
    showModal(modals.EDIT_PROJECT_CONFIG, { uuid, activeConfigUuid: visibleConfig?.uuid });
  };

  return {
    key: 'edit-configuration',
    icon: <FontAwesomeIcon icon={faPenToSquare} />,
    label: 'Edit Configuration',
    onClick: handleOnClick,
  };
};

const useVisibleConfigItems = (uuid, config) => {
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
    return [];
  }

  const items = [];

  if (config.configStatus === ConfigStatusEnum.DRAFT && config.updatedAt && config.configFile) {
    items.push({
      key: `approve-config-${configUuid}`,
      icon: <FontAwesomeIcon icon={faCodePullRequest} />,
      label: 'Request to Publish',
      onClick: handleOnApprove,
    });
  }

  if (config.configStatus === ConfigStatusEnum.READY_TO_SERVE) {
    items.push({
      key: `cancel-approval-${configUuid}`,
      icon: <FontAwesomeIcon icon={faCircleStop} />,
      label: 'Cancel Publish Request',
      onClick: handleOnCancel,
    });

    items.push({
      key: `serve-config-${configUuid}`,
      icon: <FontAwesomeIcon icon={faPlay} />,
      label: 'Publish',
      onClick: handleOnServe,
    });
  }

  if (config.configStatus === ConfigStatusEnum.SERVED) {
    items.push({
      key: `unserve-config-${configUuid}`,
      icon: <FontAwesomeIcon icon={faStop} />,
      label: 'Unpublish',
      onClick: handleOnUnserve,
    });
  }

  return items;
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
