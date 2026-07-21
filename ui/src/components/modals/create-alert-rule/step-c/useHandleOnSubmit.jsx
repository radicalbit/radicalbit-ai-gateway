import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import {
  AlertChannelEnum, AlertScopeEnum, AlertTimeAggregationEnum,
} from '@Src/constants';
import { useCreateAlertMutation } from '@State/alerts/api';
import { useFormbitContext } from '@radicalbit/formbit';

export default () => {
  const { hideModal } = useModals();
  const { isFormInvalid, submitForm } = useFormbitContext();

  const [trigger, args] = useCreateAlertMutation({ fixedCacheKey: 'create-alert' });
  const isSubmitDisabled = isFormInvalid();

  const handleOnSubmit = () => {
    if (isSubmitDisabled || args.isLoading) {
      return;
    }

    submitForm(async ({ form: formData }, setError) => {
      const data = {
        name: formData.name,
        description: formData.description ?? null,
        project: formData.project,
        route: formData.route,
        scope: AlertScopeEnum.ROUTE,
        event: formData.event,
        timeAggregation: AlertTimeAggregationEnum.INSTANT,
        channel: AlertChannelEnum.EMAIL,
        recipients: formData.recipients,
        enabled: formData.enabled ?? false,
      };

      const { error: createError } = await trigger({
        data,
        successMessage: <SuccessMessage prefix="Alert rule" strong={formData.name} suffix="created" />,
      });

      if (createError) {
        setError('silent.backend', getMessageFromQueryError(createError));
        return;
      }

      hideModal();
    });
  };

  return { handleOnSubmit, args, isSubmitDisabled };
};
