import { useVerifyProjectQuery } from '@State/projects/api';
import { skipToken } from '@reduxjs/toolkit/query';
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

const STORAGE_KEY = 'rbit-gw-projectUuid';

export default function usePersistProjectUuid() {
  const [searchParams, setSearchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const [candidate, setCandidate] = useState(() => (projectUuid ? null : localStorage.getItem(STORAGE_KEY)));

  const { isError: isCandidateError, isSuccess: isCandidateValid } = useVerifyProjectQuery(candidate ?? skipToken);

  useRestoreValidatedUuid({ candidate, isCandidateValid, setCandidate, setSearchParams });
  useDropStaleUuid({ candidate, isCandidateError, setCandidate });
  usePersistSelectedUuid(projectUuid);
}

const useRestoreValidatedUuid = ({ candidate, isCandidateValid, setCandidate, setSearchParams }) => {
  useEffect(() => {
    if (!candidate || !isCandidateValid) {
      return;
    }

    setSearchParams((prev) => {
      prev.set('projectUuid', candidate);
      return prev;
    }, { replace: true });

    setCandidate(null);
  }, [candidate, isCandidateValid, setCandidate, setSearchParams]);
};

const useDropStaleUuid = ({ candidate, isCandidateError, setCandidate }) => {
  useEffect(() => {
    if (!candidate || !isCandidateError) {
      return;
    }

    localStorage.removeItem(STORAGE_KEY);
    setCandidate(null);
  }, [candidate, isCandidateError, setCandidate]);
};

const usePersistSelectedUuid = (projectUuid) => {
  useEffect(() => {
    if (projectUuid) {
      localStorage.setItem(STORAGE_KEY, projectUuid);
    }
  }, [projectUuid]);
};
