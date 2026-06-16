import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import {
  useApproveConfigMutation,
  useGetProjectQuery,
  useUpdateConfigMutation,
} from '@State/projects/api';
import { faCodePullRequest } from '@fortawesome/free-solid-svg-icons';
import { useFormbitContext } from '@radicalbit/formbit';
import { Button, FontAwesomeIcon } from '@radicalbit/radicalbit-design-system';

function RequestToPublish({ config, projectUuid }) {
  const configUuid = config.uuid;

  const { data: project } = useGetProjectQuery(projectUuid, { skip: !projectUuid });
  const projectName = project?.name ?? '';

  const { isDirty, submitForm } = useFormbitContext();

  const [, saveArgs] = useUpdateConfigMutation({ fixedCacheKey: `update-config-${configUuid}` });
  const [triggerApprove, approveArgs] = useApproveConfigMutation({ fixedCacheKey: `approve-config-${configUuid}` });

  const isPublishDisabled = isDirty || approveArgs.isLoading || saveArgs.isLoading;

  const handleOnPublish = async () => {
    if (isPublishDisabled) {
      return;
    }

    const { error: requestError } = await triggerApprove({
      projectUuid,
      configUuid,
      successMessage: <SuccessMessage prefix="Configuration for" strong={projectName} suffix="sent for publish" />,
    });

    if (requestError) {
      submitForm((_, setError) => {
        setError('silent.backend', getMessageFromQueryError(requestError));
      });
    }
  };

  return (
    <Button
      disabled={isPublishDisabled}
      loading={approveArgs.isLoading}
      onClick={handleOnPublish}
      prefix={<FontAwesomeIcon icon={faCodePullRequest} />}
      type="primary"
    >
      Request to Publish
    </Button>
  );
}

export default RequestToPublish;
