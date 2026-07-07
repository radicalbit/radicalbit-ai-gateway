import SuccessMessage from '@Components/success-message';
import useModals, { modals } from '@Hooks/use-modals';
import { ConfigStatusEnum } from '@Src/constants';
import {
  useApproveConfigMutation,
  useCancelApprovalMutation,
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
} from '@fortawesome/free-solid-svg-icons';
import {
  Button, Dropdown, FontAwesomeIcon,
} from '@radicalbit/radicalbit-design-system';

function SlotActions({ projectUuid, projectName, config }) {
  const items = useSlotMenuItems({ projectUuid, projectName, config });

  const handleOnClick = (e) => {
    e.stopPropagation();
  };

  if (!items.length) {
    return false;
  }

  return (
    <Dropdown className="c-project-config-menu" menu={{ items }}>
      <Button onClick={handleOnClick} type="text">
        <FontAwesomeIcon icon={faEllipsisVertical} />
      </Button>
    </Dropdown>
  );
}

const useSlotMenuItems = ({ projectUuid, projectName, config }) => {
  const { showModal } = useModals();

  const configUuid = config?.uuid;

  const [triggerApprove, approveArgs] = useApproveConfigMutation({ fixedCacheKey: `approve-config-${configUuid}` });
  const [triggerCancel, cancelArgs] = useCancelApprovalMutation({ fixedCacheKey: `cancel-approval-${configUuid}` });
  const [triggerServe, serveArgs] = useServeConfigMutation({ fixedCacheKey: `serve-config-${configUuid}` });
  const [triggerUnserve, unserveArgs] = useUnserveConfigMutation({ fixedCacheKey: `unserve-config-${configUuid}` });

  const handleOnEdit = () => {
    showModal(modals.EDIT_PROJECT_CONFIG, { uuid: projectUuid, activeConfigUuid: configUuid });
  };

  const handleOnApprove = async () => {
    if (approveArgs.isLoading) {
      return;
    }

    await triggerApprove({
      projectUuid,
      configUuid,
      successMessage: <SuccessMessage prefix="Configuration for" strong={projectName} suffix="sent for publish" />,
    });
  };

  const handleOnCancel = async () => {
    if (cancelArgs.isLoading) {
      return;
    }

    await triggerCancel({
      projectUuid,
      configUuid,
      successMessage: <SuccessMessage prefix="Publish request for" strong={projectName} suffix="cancelled" />,
    });
  };

  const handleOnServe = async () => {
    if (serveArgs.isLoading) {
      return;
    }

    await triggerServe({
      projectUuid,
      configUuid,
      successMessage: <SuccessMessage prefix="Configuration for" strong={projectName} suffix="served" />,
    });
  };

  const handleOnUnserve = async () => {
    if (unserveArgs.isLoading) {
      return;
    }

    await triggerUnserve({
      projectUuid,
      configUuid,
      successMessage: <SuccessMessage prefix="Configuration for" strong={projectName} suffix="unserved" />,
    });
  };

  if (!config) {
    return [];
  }

  const items = [
    {
      key: `edit-config-${configUuid}`,
      icon: <FontAwesomeIcon icon={faPenToSquare} />,
      label: 'Edit Configuration',
      onClick: handleOnEdit,
    },
  ];

  if (config.configStatus === ConfigStatusEnum.DRAFT && config.configFile) {
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

export default SlotActions;
