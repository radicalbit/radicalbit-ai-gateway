import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import { useGetProjectQuery, useUnserveConfigMutation } from '@State/projects/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { Button } from '@radicalbit/radicalbit-design-system';

function Unpublish({ config, projectUuid }) {
  const configUuid = config.uuid;

  const { data: project } = useGetProjectQuery(projectUuid, { skip: !projectUuid });
  const projectName = project?.name ?? '';

  const { submitForm } = useFormbitContext();

  const [triggerUnserve, unserveArgs] = useUnserveConfigMutation({ fixedCacheKey: `unserve-config-${configUuid}` });

  const handleOnUnserve = async () => {
    if (unserveArgs.isLoading) {
      return;
    }

    const { error: requestError } = await triggerUnserve({
      projectUuid,
      configUuid,
      successMessage: <SuccessMessage prefix="Configuration for" strong={projectName} suffix="unserved" />,
    });

    if (requestError) {
      submitForm((_, setError) => {
        setError('silent.backend', getMessageFromQueryError(requestError));
      });
    }
  };

  return (
    <Button
      disabled={unserveArgs.isLoading}
      loading={unserveArgs.isLoading}
      onClick={handleOnUnserve}
      type="primary"
    >
      Unpublish
    </Button>
  );
}

export default Unpublish;
