import Lucide from '@Components/lucide';
import SuccessMessage from '@Components/success-message';
import useModals, { modals } from '@Hooks/use-modals';
import { ConfigStatusEnum } from '@Src/constants';
import {
  useApproveConfigMutation,
  useCancelApprovalMutation,
  useServeConfigMutation,
  useUnserveConfigMutation,
} from '@State/projects/api';
import { Button, Dropdown } from '@radicalbit/radicalbit-design-system';
import {
  CircleStop,
  EllipsisVertical,
  GitPullRequest,
  Play,
  Square,
  SquarePen,
} from 'lucide-react';

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
        <Lucide icon={EllipsisVertical} />
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
      icon: <Lucide icon={SquarePen} />,
      label: 'Edit Configuration',
      onClick: handleOnEdit,
    },
  ];

  if (config.configStatus === ConfigStatusEnum.DRAFT && config.updatedAt && config.configFile) {
    items.push({
      key: `approve-config-${configUuid}`,
      icon: <Lucide icon={GitPullRequest} />,
      label: 'Request to Publish',
      onClick: handleOnApprove,
    });
  }

  if (config.configStatus === ConfigStatusEnum.READY_TO_SERVE) {
    items.push({
      key: `cancel-approval-${configUuid}`,
      icon: <Lucide icon={CircleStop} />,
      label: 'Cancel Publish Request',
      onClick: handleOnCancel,
    });

    items.push({
      key: `serve-config-${configUuid}`,
      icon: <Lucide icon={Play} />,
      label: 'Publish',
      onClick: handleOnServe,
    });
  }

  if (config.configStatus === ConfigStatusEnum.SERVED) {
    items.push({
      key: `unserve-config-${configUuid}`,
      icon: <Lucide icon={Square} />,
      label: 'Unpublish',
      onClick: handleOnUnserve,
    });
  }

  return items;
};

export default SlotActions;
