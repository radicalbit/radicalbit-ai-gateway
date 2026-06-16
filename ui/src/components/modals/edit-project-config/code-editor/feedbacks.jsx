import { ConfigStatusEnum } from '@Src/constants';
import { useFormbitContext } from '@radicalbit/formbit';
import { Alert } from '@radicalbit/radicalbit-design-system';

function Feedbacks({ config }) {
  switch (config.configStatus) {
    case ConfigStatusEnum.READY_TO_SERVE:
      return <FeedbacksReadyToServe />;

    case ConfigStatusEnum.DRAFT:
    case ConfigStatusEnum.SERVED:
    default:
      return <FeedbacksDefault />;
  }
}

function FeedbacksDefault() {
  const { error } = useFormbitContext();
  const backendError = error('silent.backend');

  if (backendError) {
    return <Alert closable message={backendError} showIcon type="error" />;
  }

  return false;
}

function FeedbacksReadyToServe() {
  const { error } = useFormbitContext();
  const backendError = error('silent.backend');

  if (backendError) {
    return <Alert closable message={backendError} showIcon type="error" />;
  }

  return <Alert closable message="Publish request submitted for approval. The admin has been notified." showIcon type="warning" />;
}

export default Feedbacks;
