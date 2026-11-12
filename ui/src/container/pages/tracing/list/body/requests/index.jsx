import Lucide from '@Components/lucide';
import { useGetRequestsWithRange } from '@State/requests/vertical-hooks';
import {
  Board,
  Button,
  Skeleton,
  Void,
} from '@radicalbit/radicalbit-design-system';
import { Inbox, TriangleAlert } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { useNavigationType, useSearchParams } from 'react-router-dom';
import { FILTER_PARAMS, REQUESTS_PAGE_PARAM, SELECTED_REQUEST_PARAM } from './constants';
import RequestPanel from './panel';
import RequestsList from './list';

function Requests() {
  const [searchParams] = useSearchParams();
  const page = Number(searchParams.get(REQUESTS_PAGE_PARAM)) || 1;

  const {
    data, isError, isFetching, isLoading, isSuccess, refetch,
  } = useGetRequestsWithRange({ page });
  const items = data?.items ?? [];
  const total = data?.total;

  const isPageOutOfRange = items.length === 0 && total > 0;

  useClearSelectionOnFilterChange();

  useResetPageWhenOutOfRange(isPageOutOfRange);

  if (isLoading) {
    return (
      <div className="flex flex-row flex-wrap items-start gap-4">
        <div className="c-observability__pane">
          <Board main={<Skeleton active block />} width="100%" />
        </div>

        <div className="c-observability__pane">
          <Board main={<Skeleton active block />} width="100%" />
        </div>
      </div>
    );
  }

  if (isError) {
    return <IsError isFetching={isFetching} refetch={refetch} />;
  }

  if (items.length === 0 && !isPageOutOfRange) {
    return <IsEmpty />;
  }

  if (!isSuccess || isPageOutOfRange) {
    return false;
  }

  return (
    <div className="flex flex-row flex-wrap items-start gap-4">
      <div className="c-observability__pane">
        <RequestsList />
      </div>

      <div className="c-observability__pane c-observability__panel">
        <RequestPanel />
      </div>
    </div>
  );
}

function IsEmpty() {
  return (
    <Board
      main={(
        <Void
          description="No request matches the filters. Try a wider time range or fewer filters."
          image={<Lucide icon={Inbox} />}
          size="small"
          title="No requests"
        />
      )}
      width="100%"
    />
  );
}

function IsError({ isFetching, refetch }) {
  return (
    <Board
      main={(
        <Void
          actions={<Button loading={isFetching} onClick={refetch}>Retry</Button>}
          description={(
            <>
              This might be temporary
              <br />
              please retry later
            </>
          )}
          image={<Lucide icon={TriangleAlert} />}
          title="Unable to load requests"
        />
      )}
      width="100%"
    />
  );
}

function useClearSelectionOnFilterChange() {
  const navigationType = useNavigationType();
  const [searchParams, setSearchParams] = useSearchParams();
  const filtersKey = FILTER_PARAMS.map((name) => searchParams.getAll(name).join(',')).join('|');

  const previousFiltersKey = useRef(filtersKey);

  useEffect(() => {
    if (previousFiltersKey.current === filtersKey) {
      return;
    }

    previousFiltersKey.current = filtersKey;

    if (navigationType !== 'PUSH') {
      return;
    }

    setSearchParams((prev) => {
      prev.delete(SELECTED_REQUEST_PARAM);
      prev.delete(REQUESTS_PAGE_PARAM);
      return prev;
    }, { replace: true });
  }, [filtersKey, navigationType, setSearchParams]);
}

function useResetPageWhenOutOfRange(isPageOutOfRange) {
  const [, setSearchParams] = useSearchParams();

  useEffect(() => {
    if (!isPageOutOfRange) {
      return;
    }

    setSearchParams((prev) => {
      prev.delete(REQUESTS_PAGE_PARAM);
      prev.delete(SELECTED_REQUEST_PARAM);
      return prev;
    }, { replace: true });
  }, [isPageOutOfRange, setSearchParams]);
}

export default Requests;
