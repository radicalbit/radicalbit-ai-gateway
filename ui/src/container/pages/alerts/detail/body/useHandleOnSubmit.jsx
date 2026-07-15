import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import {
  AlertChannelEnum, AlertScopeEnum, AlertTimeAggregationEnum,
} from '@Src/constants';
import { useEditAlertMutation } from '@State/alerts/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { useCallback } from 'react';
import { useParams } from 'react-router-dom';

export default () => {
  const { uuid } = useParams();
  const { isFormInvalid, isDirty, submitForm } = useFormbitContext();

  const [trigger, args] = useEditAlertMutation({ fixedCacheKey: `edit-alert-${uuid}` });
  const isSubmitDisabled = !isDirty || isFormInvalid();

  const handleOnSubmit = useCallback(() => {
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
      };

      const { error: editError } = await trigger({
        uuid,
        data,
        successMessage: <SuccessMessage prefix="Alert rule" strong={formData.name} suffix="updated" />,
      });

      if (editError) {
        setError('silent.backend', getMessageFromQueryError(editError));
      }
    });
  }, [args.isLoading, isSubmitDisabled, submitForm, trigger, uuid]);

  return { handleOnSubmit, args, isSubmitDisabled };
};
