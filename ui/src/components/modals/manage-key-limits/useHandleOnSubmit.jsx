import { EXPIRED_LIMITS_MESSAGE } from '@Components/limits/constants';
import { formatCount, getNewLimitsErrors, isLimitComplete } from '@Components/limits/helpers';
import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import { useCreateKeyLimitsMutation, useGetKeyQuery } from '@State/keys/api';
import { FCK_CREATE_KEY_LIMITS } from '@State/keys/fixed-cache-key';
import { useFormbitContext } from '@radicalbit/formbit';
import { getInitialValues } from './schema';

const METHOD_NOT_ALLOWED = 405;

const ROW_LOC_INDEX = 2;

// pydantic prefixes the messages of its validators with "Value error, "
const getValidationMessage = ({ msg }) => msg.replace(/^Value error, /, '');

const getBackendErrors = (queryError) => {
  if (queryError?.status === METHOD_NOT_ALLOWED) {
    return { message: EXPIRED_LIMITS_MESSAGE, rows: {} };
  }

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

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const name = data?.name;
  const limits = data?.limits ?? [];

  const [trigger, args] = useCreateKeyLimitsMutation({ fixedCacheKey: `${FCK_CREATE_KEY_LIMITS}-${uuid}` });

  const hasRowErrors = getNewLimitsErrors({ limits, rows }).some(Boolean);
  const isSubmitDisabled = isFormInvalid() || hasRowErrors || !rows.every(isLimitComplete) || args.isLoading;

  const handleOnSubmit = () => {
    if (isSubmitDisabled) {
      return;
    }

    submitForm(async ({ form: formData }, setError) => {
      const payload = formData.limits.map(({ algorithm, category, value, windowSize }) => ({
        algorithm, category, value, windowSize,
      }));

      const { error } = await trigger({
        uuid,
        data: { limits: payload },
        successMessage: <SuccessMessage prefix={`${formatCount(payload.length, 'limit')} added to`} strong={name} />,
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
