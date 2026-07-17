import Lucide from '@Components/lucide';
import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import {
  useCancelApprovalMutation,
  useGetProjectQuery,
  useServeConfigMutation,
} from '@State/projects/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { Button } from '@radicalbit/radicalbit-design-system';
import { Check } from 'lucide-react';

function Publish({ config, projectUuid }) {
  const configUuid = config.uuid;

  const { data: project } = useGetProjectQuery(projectUuid, { skip: !projectUuid });
  const projectName = project?.name ?? '';

  const { submitForm } = useFormbitContext();

  const [, cancelArgs] = useCancelApprovalMutation({ fixedCacheKey: `cancel-approval-${configUuid}` });
  const [triggerServe, serveArgs] = useServeConfigMutation({ fixedCacheKey: `serve-config-${configUuid}` });

  const isBusy = cancelArgs.isLoading || serveArgs.isLoading;

  const handleOnServe = async () => {
    if (isBusy) {
      return;
    }

    const { error: requestError } = await triggerServe({
      projectUuid,
      configUuid,
      successMessage: <SuccessMessage prefix="Configuration for" strong={projectName} suffix="served" />,
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
      loading={serveArgs.isLoading}
      onClick={handleOnServe}
      prefix={<Lucide icon={Check} />}
      type="primary"
    >
      Publish
    </Button>
  );
}

export default Publish;
