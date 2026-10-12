import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import {
  AlertChannelEnum, AlertScopeEnum, AlertTimeAggregationEnum,
} from '@Src/constants';
import { useCreateAlertMutation } from '@State/alerts/api';
import { FCK_CREATE_ALERT } from '@State/alerts/fixed-cache-key';
import { useFormbitContext } from '@radicalbit/formbit';

export default () => {
  const { hideModal } = useModals();
  const { isFormInvalid, submitForm } = useFormbitContext();

  const [trigger, { isLoading }] = useCreateAlertMutation({ fixedCacheKey: FCK_CREATE_ALERT });
  const isSubmitDisabled = isFormInvalid() || isLoading;

  // `enabled` comes from the button the user picked, not from a form field
  const handleOnSubmit = ({ enabled }) => {
    if (isSubmitDisabled) {
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
        enabled,
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

  return { handleOnSubmit, isSubmitDisabled, isLoading };
};
