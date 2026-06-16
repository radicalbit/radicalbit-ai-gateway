import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import {
  useCancelApprovalMutation,
  useGetProjectQuery,
  useServeConfigMutation,
} from '@State/projects/api';
import { faCircleStop } from '@fortawesome/free-solid-svg-icons';
import { useFormbitContext } from '@radicalbit/formbit';
import { Button, FontAwesomeIcon } from '@radicalbit/radicalbit-design-system';

function CancelPublishRequest({ config, projectUuid }) {
  const configUuid = config.uuid;

  const { data: project } = useGetProjectQuery(projectUuid, { skip: !projectUuid });
  const projectName = project?.name ?? '';

  const { submitForm } = useFormbitContext();

  const [triggerCancel, cancelArgs] = useCancelApprovalMutation({ fixedCacheKey: `cancel-approval-${configUuid}` });
  const [, serveArgs] = useServeConfigMutation({ fixedCacheKey: `serve-config-${configUuid}` });

  const isBusy = cancelArgs.isLoading || serveArgs.isLoading;

  const handleOnCancel = async () => {
    if (isBusy) {
      return;
    }

    const { error: requestError } = await triggerCancel({
      projectUuid,
      configUuid,
      successMessage: <SuccessMessage prefix="Publish request for" strong={projectName} suffix="cancelled" />,
    });

    if (requestError) {
      submitForm((_, setError) => {
        setError('silent.backend', getMessageFromQueryError(requestError));
      });
    }
  };

  return (
    <Button
      disabled={isBusy}
      loading={cancelArgs.isLoading}
      onClick={handleOnCancel}
      prefix={<FontAwesomeIcon icon={faCircleStop} />}
      type="secondary"
    >
      Cancel Publish Request
    </Button>
  );
}

export default CancelPublishRequest;
