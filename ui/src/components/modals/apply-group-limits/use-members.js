import useModals from '@Hooks/use-modals';
import { useGetGroupQuery } from '@State/groups/api';
import { useGetKeysQuery } from '@State/keys/api';
import { useMemo } from 'react';

export default () => {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data: group } = useGetGroupQuery(uuid, { skip: !uuid });
  const groupKeys = group?.keys;

  const { data: credentials } = useGetKeysQuery();

  const members = useMemo(() => groupKeys ?? [], [groupKeys]);
  const limitsByKey = useMemo(
    () => Object.fromEntries((credentials ?? []).map(({ limits, uuid: keyUuid }) => [keyUuid, limits ?? []])),
    [credentials],
  );

  return { members, limitsByKey };
};
