import { useVerifyProjectQuery } from '@State/projects/api';
import { skipToken } from '@reduxjs/toolkit/query';
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

const STORAGE_KEY = 'rbit-gw-projectUuid';

export default function usePersistProjectUuid() {
  const [searchParams, setSearchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const [candidate, setCandidate] = useState(() => (projectUuid ? null : localStorage.getItem(STORAGE_KEY)));

  const { isError, isSuccess } = useVerifyProjectQuery(candidate ?? skipToken);

  useRestoreValidatedUuid({ candidate, isSuccess, setCandidate, setSearchParams });
  useDropStaleUuid({ candidate, isError, setCandidate });
  usePersistSelectedUuid(projectUuid);
}

const useRestoreValidatedUuid = ({ candidate, isSuccess, setCandidate, setSearchParams }) => {
  useEffect(() => {
    if (!candidate || !isSuccess) {
      return;
    }

    setSearchParams((prev) => {
      prev.set('projectUuid', candidate);
      return prev;
    }, { replace: true });

    setCandidate(null);
  }, [candidate, isSuccess, setCandidate, setSearchParams]);
};

const useDropStaleUuid = ({ candidate, isError, setCandidate }) => {
  useEffect(() => {
    if (!candidate || !isError) {
      return;
    }

    localStorage.removeItem(STORAGE_KEY);
    setCandidate(null);
  }, [candidate, isError, setCandidate]);
};

const usePersistSelectedUuid = (projectUuid) => {
  useEffect(() => {
    if (projectUuid) {
      localStorage.setItem(STORAGE_KEY, projectUuid);
    }
  }, [projectUuid]);
};
