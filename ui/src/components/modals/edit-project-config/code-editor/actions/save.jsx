import Lucide from '@Components/lucide';
import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import { useGetProjectQuery, useUpdateConfigMutation } from '@State/projects/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { Button } from '@radicalbit/radicalbit-design-system';
import { Save as SaveIcon } from 'lucide-react';

function Save({ config, projectUuid }) {
  const configUuid = config.uuid;

  const { data: project } = useGetProjectQuery(projectUuid, { skip: !projectUuid });
  const projectName = project?.name ?? '';

  const { isDirty, isFormInvalid, submitForm } = useFormbitContext();

  const [triggerSave, saveArgs] = useUpdateConfigMutation({ fixedCacheKey: `update-config-${configUuid}` });

  const isSaveDisabled = !isDirty || isFormInvalid() || saveArgs.isLoading;

  const handleOnSave = () => {
    if (isSaveDisabled) {
      return;
    }

    submitForm(async ({ form: formData }, setError) => {
      const { error: requestError } = await triggerSave({
        projectUuid,
        configUuid,
        data: { configFile: formData.configs?.[configUuid] },
        successMessage: <SuccessMessage prefix="Configuration for" strong={projectName} suffix="saved as draft" />,
      });

      if (requestError) {
        setError('silent.backend', getMessageFromQueryError(requestError));
      }
    });
  };

  return (
    <Button
      disabled={isSaveDisabled}
      loading={saveArgs.isLoading}
      onClick={handleOnSave}
      prefix={<Lucide icon={SaveIcon} />}
      type="primary"
    >
      Save
    </Button>
  );
}

export default Save;
