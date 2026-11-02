import { useCallback } from 'react';
import { useCreateKeyLimitsMutation, useUpdateKeyLimitValueMutation } from './api';
import { FCK_CREATE_KEY_LIMITS, FCK_REPLACE_KEY_LIMIT_CREATE, FCK_UPDATE_KEY_LIMIT_VALUE } from './fixed-cache-key';

export const useKeyLimitSaveWarnings = (uuid) => {
  const [, addState] = useCreateKeyLimitsMutation({ fixedCacheKey: `${FCK_CREATE_KEY_LIMITS}-${uuid}` });
  const [, updateState] = useUpdateKeyLimitValueMutation({ fixedCacheKey: `${FCK_UPDATE_KEY_LIMIT_VALUE}-${uuid}` });
  const [, replaceState] = useCreateKeyLimitsMutation({ fixedCacheKey: `${FCK_REPLACE_KEY_LIMIT_CREATE}-${uuid}` });

  const [latest] = [addState, updateState, replaceState]
    .filter(({ isSuccess }) => isSuccess)
    .sort((a, b) => b.fulfilledTimeStamp - a.fulfilledTimeStamp);
  const warnings = latest?.data?.warnings ?? [];

  const resetAdd = addState.reset;
  const resetUpdate = updateState.reset;
  const resetReplace = replaceState.reset;

  const clearWarnings = useCallback(() => {
    resetAdd();
    resetUpdate();
    resetReplace();
  }, [resetAdd, resetReplace, resetUpdate]);

  return { clearWarnings, warnings };
};
