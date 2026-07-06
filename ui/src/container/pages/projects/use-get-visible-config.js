import { ConfigStatusEnum } from '@Src/constants';

const CONFIG_STATUS_SCORE = {
  [ConfigStatusEnum.DRAFT]: 0,
  [ConfigStatusEnum.READY_TO_SERVE]: 1,
  [ConfigStatusEnum.SERVED]: 2,
};

/**
 * Picks the single config to surface for a project row.
 *
 * Scoring: DRAFT=0, READY_TO_SERVE=1, SERVED=2. The highest score wins; on a
 * tie the slot with the most recent updatedAt is chosen.
 */
const useGetVisibleConfig = (configs = []) => {
  if (!configs.length) {
    return null;
  }

  return [...configs].sort((a, b) => {
    const scoreDiff = (CONFIG_STATUS_SCORE[b.configStatus] ?? 0) - (CONFIG_STATUS_SCORE[a.configStatus] ?? 0);

    if (scoreDiff !== 0) {
      return scoreDiff;
    }

    return (b.updatedAt ?? '').localeCompare(a.updatedAt ?? '');
  })[0];
};

export default useGetVisibleConfig;
