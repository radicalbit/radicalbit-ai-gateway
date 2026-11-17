import { modals } from '@Hooks/use-modals';
import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { SPAN_PARAM, SPAN_TAB_PARAM } from './constants';

function useCloseRequestDetail() {
  const [, setSearchParams] = useSearchParams();

  return useCallback(() => {
    setSearchParams((prev) => {
      prev.delete(modals.QUERY_NAME);
      prev.delete(SPAN_PARAM);
      prev.delete(SPAN_TAB_PARAM);
      return prev;
    });
  }, [setSearchParams]);
}

export default useCloseRequestDetail;
