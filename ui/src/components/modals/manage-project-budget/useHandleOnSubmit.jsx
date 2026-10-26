import {
  asBudgets, formatCount, getNewLimitsErrors, isLimitComplete,
} from '@Components/limits/helpers';
import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import { useCreateProjectBudgetLimitsMutation, useGetProjectQuery } from '@State/projects/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { getInitialValues } from './schema';

const ROW_LOC_INDEX = 2;

// pydantic prefixes the messages of its validators with "Value error, "
const getValidationMessage = ({ msg }) => msg.replace(/^Value error, /, '');

const getBackendErrors = (queryError) => {
  const detail = queryError?.data?.detail;

  if (!Array.isArray(detail)) {
    return { message: getMessageFromQueryError(queryError), rows: {} };
  }

  const rows = Object.fromEntries(detail
    .filter(({ loc }) => Number.isInteger(loc?.[ROW_LOC_INDEX]))
    .map((item) => [item.loc[ROW_LOC_INDEX], getValidationMessage(item)]));
  const general = detail.find(({ loc }) => !Number.isInteger(loc?.[ROW_LOC_INDEX]));

  return { message: general ? getValidationMessage(general) : undefined, rows };
};

export default () => {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form, initialize, isFormInvalid, submitForm } = useFormbitContext();
  const rows = form?.limits ?? [];

  const { data } = useGetProjectQuery(uuid, { skip: !uuid });
  const name = data?.name;
  const limits = asBudgets(data?.limits);
  const isBlocked = (data?.routeBudgets?.published ?? []).length > 0;

  const [trigger, args] = useCreateProjectBudgetLimitsMutation({ fixedCacheKey: `create-project-budget-${uuid}` });

  const hasRowErrors = getNewLimitsErrors({ limits, rows }).some(Boolean);
  const isSubmitDisabled = isBlocked || isFormInvalid() || hasRowErrors || !rows.every(isLimitComplete) || args.isLoading;

  const handleOnSubmit = () => {
    if (isSubmitDisabled) {
      return;
    }

    submitForm(async ({ form: formData }, setError) => {
      const payload = formData.limits.map(({ algorithm, value, windowSize }) => ({ algorithm, value, windowSize }));

      const { error } = await trigger({
        uuid,
        data: { limits: payload },
        successMessage: <SuccessMessage prefix={`${formatCount(payload.length, 'budget')} added to`} strong={name} />,
      });

      if (error) {
        const backendErrors = getBackendErrors(error);

        setError('silent.backend', backendErrors.message);
        payload.forEach((_, index) => {
          setError(`silent.limits.${index}`, backendErrors.rows[index]);
        });

        return;
      }

      initialize(getInitialValues());
    });
  };

  return { handleOnSubmit, args, isSubmitDisabled };
};
