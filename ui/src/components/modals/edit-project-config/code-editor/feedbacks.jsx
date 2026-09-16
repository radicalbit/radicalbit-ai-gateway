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
    return <Alert closable showIcon title={backendError} type="error" />;
  }

  return false;
}

function FeedbacksReadyToServe() {
  const { error } = useFormbitContext();
  const backendError = error('silent.backend');

  if (backendError) {
    return <Alert closable showIcon title={backendError} type="error" />;
  }

  return <Alert closable showIcon title="Publish request submitted for approval." type="warning" />;
}

export default Feedbacks;
