import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import { useApplyGroupLimitsMutation, useGetGroupQuery } from '@State/groups/api';
import { FCK_APPLY_GROUP_LIMITS } from '@State/groups/fixed-cache-key';
import { useGetKeysQuery } from '@State/keys/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { areRowsValid, getConflicts, getPreview } from './helpers';
import useMembers from './use-members';
import useTouchedCount from './use-touched-count';

const ROW_LOC_INDEX = 2;

const getValidationMessage = ({ msg }) => msg.replace(/^Value error, /, '');

const isLimitsLoc = (loc) => loc?.[1] === 'limits' && Number.isInteger(loc?.[ROW_LOC_INDEX]);

const getBackendErrors = (queryError) => {
  const detail = queryError?.data?.detail;

  if (!Array.isArray(detail)) {
    return { message: getMessageFromQueryError(queryError), rows: {} };
  }

  const rows = Object.fromEntries(detail
    .filter(({ loc }) => isLimitsLoc(loc))
    .map((item) => [item.loc[ROW_LOC_INDEX], getValidationMessage(item)]));
  const general = detail.find(({ loc }) => !isLimitsLoc(loc));

  return { message: general ? getValidationMessage(general) : undefined, rows };
};

export default () => {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form, isFormInvalid, submitForm } = useFormbitContext();
  const rows = form?.limits ?? [];

  const { members, limitsByKey } = useMembers();

  const touchedCount = useTouchedCount();

  const { isFetching: isFetchingGroup } = useGetGroupQuery(uuid, { skip: !uuid });

  const { isFetching: isFetchingKeys } = useGetKeysQuery();

  const [trigger, args] = useApplyGroupLimitsMutation({ fixedCacheKey: `${FCK_APPLY_GROUP_LIMITS}-${uuid}` });

  const isFetching = isFetchingGroup || isFetchingKeys;
  const isSubmitDisabled = isFormInvalid() || !areRowsValid(rows) || !touchedCount || isFetching || args.isLoading;

  const handleOnSubmit = () => {
    if (isSubmitDisabled) {
      return;
    }

    submitForm(async ({ form: formData }, setError) => {
      const overwritten = new Set(formData.overwrite);
      const limits = formData.limits.map(({ algorithm, category, value, windowSize }) => ({
        algorithm, category, value, windowSize,
      }));
      const skip = getConflicts(getPreview({ limitsByKey, members, rows: limits }))
        .filter(({ key }) => !overwritten.has(key))
        .map(({ limit, member }) => ({
          keyUuid: member.uuid,
          category: limit.category,
          algorithm: limit.algorithm,
          windowSize: limit.windowSize,
        }));

      const { error } = await trigger({ uuid, data: { limits, skip } });

      if (error) {
        const backendErrors = getBackendErrors(error);

        setError('silent.backend', backendErrors.message);
        limits.forEach((_, index) => {
          setError(`silent.limits.${index}`, backendErrors.rows[index]);
        });
      }
    });
  };

  return { handleOnSubmit, args, isSubmitDisabled };
};
