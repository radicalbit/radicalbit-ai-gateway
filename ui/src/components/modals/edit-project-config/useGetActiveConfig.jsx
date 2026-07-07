import useModals, { modals } from '@Hooks/use-modals';
import { useGetProjectQuery } from '@State/projects/api';
import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';

const LEGACY_ACTIVE_CONFIG_QP = 'activeConfigUuid';

/**
 * Resolves the currently active config slot for the edit-project-config modal.
 *
 * The active slot is tracked inside the modal payload (`activeConfigUuid`). When
 * the payload holds a value we use it; otherwise the first config in the array
 * (Slot A) is active. Keeping it in the payload means it is cleared automatically
 * by `hideModal` (which drops the whole `modal` query param).
 */
const useGetActiveConfig = () => {
  const { showModal, modalPayload } = useModals();
  const projectUuid = modalPayload?.data?.uuid;
  const activeConfigUuid = modalPayload?.data?.activeConfigUuid;

  const [searchParams, setSearchParams] = useSearchParams();

  const { data: project } = useGetProjectQuery(projectUuid, { skip: !projectUuid });
  const configs = project?.configs ?? [];

  const activeConfig = configs.find((c) => c.uuid === activeConfigUuid) ?? configs[0];

  // Drop any leftover standalone `activeConfigUuid` query param (legacy: the
  // active slot now lives in the modal payload). `showModal` preserves existing
  // params, so an orphan one would otherwise stick to the URL.
  useEffect(() => {
    if (searchParams.has(LEGACY_ACTIVE_CONFIG_QP)) {
      setSearchParams((prev) => {
        prev.delete(LEGACY_ACTIVE_CONFIG_QP);
        return prev;
      }, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const selectConfig = (uuid) => {
    showModal(modals.EDIT_PROJECT_CONFIG, { uuid: projectUuid, activeConfigUuid: uuid });
  };

  return {
    activeConfig,
    configs,
    projectUuid,
    selectConfig,
  };
};

export default useGetActiveConfig;
