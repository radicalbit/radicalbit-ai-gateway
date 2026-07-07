import { ConfigStatusEnum } from '@Src/constants';
import CancelPublishRequest from './cancel-publish-request';
import Close from './close';
import Publish from './publish';
import RequestToPublish from './request-to-publish';
import Save from './save';
import Unpublish from './unpublish';

function Actions({ config, projectUuid }) {
  switch (config.configStatus) {
    case ConfigStatusEnum.READY_TO_SERVE:
      return <ActionsReadyToServe config={config} projectUuid={projectUuid} />;

    case ConfigStatusEnum.SERVED:
      return <ActionsServed config={config} projectUuid={projectUuid} />;

    case ConfigStatusEnum.DRAFT: {
      if (config.updatedAt) {
        return <ActionsDraft config={config} projectUuid={projectUuid} />;
      }

      return <ActionsEmpty config={config} projectUuid={projectUuid} />;
    }

    default:
      return <ActionsEmpty config={config} projectUuid={projectUuid} />;
  }
}

function ActionsEmpty({ config, projectUuid }) {
  return (
    <div className="flex gap-4 items-center">
      <Close />

      <Save config={config} projectUuid={projectUuid} />
    </div>
  );
}

function ActionsDraft({ config, projectUuid }) {
  return (
    <div className="flex gap-4 items-center">
      <Close />

      <Save config={config} projectUuid={projectUuid} />

      <RequestToPublish config={config} projectUuid={projectUuid} />
    </div>
  );
}

function ActionsReadyToServe({ config, projectUuid }) {
  return (
    <div className="flex gap-4 items-center">
      <Close />

      <CancelPublishRequest config={config} projectUuid={projectUuid} />

      <Publish config={config} projectUuid={projectUuid} />
    </div>
  );
}

function ActionsServed({ config, projectUuid }) {
  return (
    <div className="flex gap-4 items-center">
      <Close />

      <Unpublish config={config} projectUuid={projectUuid} />
    </div>
  );
}

export default Actions;
