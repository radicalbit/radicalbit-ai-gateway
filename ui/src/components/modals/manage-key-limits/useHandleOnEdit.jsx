import { EXPIRED_LIMITS_MESSAGE, LIMIT_CATEGORY_LABELS, WINDOW_TYPE_LABELS } from '@Components/limits/constants';
import focusConfirmQuestion from '@Components/limits/focus-confirm-question';
import focusLimitMenu from '@Components/limits/focus-limit-menu';
import { formatLimitWindow, getNewLimitsErrors, isLimitComplete } from '@Components/limits/helpers';
import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import { useGetKeyQuery, useUpdateKeyLimitValueMutation } from '@State/keys/api';
import { FCK_UPDATE_KEY_LIMIT_VALUE } from '@State/keys/fixed-cache-key';
import { useFormbitContext } from '@radicalbit/formbit';
import { ScreenEnum, getInitialValues } from './schema';

const METHOD_NOT_ALLOWED = 405;

const getErrorMessage = (queryError) => {
  if (queryError?.status === METHOD_NOT_ALLOWED) {
    return EXPIRED_LIMITS_MESSAGE;
  }

  const detail = queryError?.data?.detail;

  if (Array.isArray(detail) && detail.length) {
    return detail[0].msg.replace(/^Value error, /, '');
  }

  return getMessageFromQueryError(queryError);
};

export default () => {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form, initialize, isFormInvalid, write } = useFormbitContext();
  const limitUuid = form?.__metadata?.limitUuid;
  const row = form?.limits?.[0];

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const name = data?.name;
  const limits = data?.limits ?? [];
  const limit = limits.find((item) => item.uuid === limitUuid);

  const [trigger, args] = useUpdateKeyLimitValueMutation({ fixedCacheKey: `${FCK_UPDATE_KEY_LIMIT_VALUE}-${limitUuid}` });

  const otherLimits = limits.filter((item) => item.uuid !== limitUuid);
  const [duplicateError] = getNewLimitsErrors({ limits: otherLimits, rows: row ? [row] : [] });
  const isWindowChanged = row?.algorithm !== limit?.algorithm || row?.windowSize !== limit?.windowSize;
  const isMaxChanged = row?.value !== limit?.value;
  const isSaveDisabled = !row || !isLimitComplete(row) || isFormInvalid() || !!duplicateError || (!isMaxChanged && !isWindowChanged) || args.isLoading;
  const errorMessage = args.isError ? getErrorMessage(args.error) : undefined;
  const label = `${LIMIT_CATEGORY_LABELS[limit?.category]} ${formatLimitWindow(limit?.windowSize)} · ${WINDOW_TYPE_LABELS[limit?.algorithm]}`;

  const handleOnSave = async () => {
    if (isSaveDisabled) {
      return;
    }

    if (isWindowChanged) {
      write('__metadata.screen', ScreenEnum.EDIT_CONFIRM);
      focusConfirmQuestion();

      return;
    }

    const { error } = await trigger({
      uuid,
      limitUuid,
      data: { value: row.value },
      successMessage: <SuccessMessage prefix="Limit" strong={label} suffix={`updated on ${name}`} />,
    });

    if (error) {
      return;
    }

    initialize(getInitialValues());
    focusLimitMenu(limitUuid);
  };

  const handleOnCancel = () => {
    args.reset();
    initialize(getInitialValues());
    focusLimitMenu(limitUuid);
  };

  return {
    args, duplicateError, errorMessage, handleOnCancel, handleOnSave, isSaveDisabled, isWindowChanged,
  };
};
