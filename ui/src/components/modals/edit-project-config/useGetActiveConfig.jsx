import useModals from '@Hooks/use-modals';
import { useGetProjectQuery } from '@State/projects/api';
import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';

const ACTIVE_CONFIG_QP = 'activeConfigUuid';

/**
 * Resolves the currently active config slot for the edit-project-config modal.
 *
 * The active slot is tracked in the `activeConfigUuid` query param. When the QP
 * holds a value we use it; otherwise the first config in the array (Slot A) is
 * active. The QP is seeded with the default on mount so the rest of the tree
 * always has a concrete uuid to key form writes/submit on.
 */
const useGetActiveConfig = () => {
  const { modalPayload } = useModals();
  const projectUuid = modalPayload?.data?.uuid;

  const { data: project } = useGetProjectQuery(projectUuid, { skip: !projectUuid });
  const configs = project?.configs ?? [];

  const [searchParams, setSearchParams] = useSearchParams();
  const activeConfigUuid = searchParams.get(ACTIVE_CONFIG_QP);

  const defaultConfigUuid = configs[0]?.uuid;
  const activeConfig = configs.find((c) => c.uuid === activeConfigUuid) ?? configs[0];

  useEffect(() => {
    if (!activeConfigUuid && defaultConfigUuid) {
      setSearchParams((prev) => {
        prev.set(ACTIVE_CONFIG_QP, defaultConfigUuid);
        return prev;
      }, { replace: true });
    }
  }, [activeConfigUuid, defaultConfigUuid, setSearchParams]);

  const selectConfig = (uuid) => {
    setSearchParams((prev) => {
      prev.set(ACTIVE_CONFIG_QP, uuid);
      return prev;
    });
  };

  return {
    activeConfig,
    configs,
    projectUuid,
    selectConfig,
  };
};

export default useGetActiveConfig;
