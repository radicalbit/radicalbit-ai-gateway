import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import { useApplyGroupLimitsMutation } from '@State/groups/api';
import { useGetKeysQuery } from '@State/keys/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { areRowsValid, getConflicts, getPreview } from './helpers';
import useMembers from './use-members';

const ROW_LOC_INDEX = 2;

// pydantic prefixes the messages of its validators with "Value error, "
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

export const getFixedCacheKey = (uuid) => `apply-group-limits-${uuid}`;

export default () => {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form, isFormInvalid, submitForm } = useFormbitContext();
  const rows = form?.limits ?? [];

  const { members, limitsByKey } = useMembers();

  // Until the credentials are fresh, a conflict could be missing from the preview, and so from skip
  const { isFetching } = useGetKeysQuery();

  const [trigger, args] = useApplyGroupLimitsMutation({ fixedCacheKey: getFixedCacheKey(uuid) });

  const isSubmitDisabled = isFormInvalid() || !areRowsValid(rows) || !members.length || isFetching || args.isLoading;

  const handleOnSubmit = () => {
    if (isSubmitDisabled) {
      return;
    }

    submitForm(async ({ form: formData }, setError) => {
      const overwrite = new Set(formData.overwrite);
      const limits = formData.limits.map(({ algorithm, category, value, windowSize }) => ({
        algorithm, category, value, windowSize,
      }));
      // A conflict the user didn't choose to overwrite is skipped: the backend overwrites what is not listed
      const skip = getConflicts(getPreview({ limitsByKey, members, rows: limits }))
        .filter(({ key }) => !overwrite.has(key))
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
