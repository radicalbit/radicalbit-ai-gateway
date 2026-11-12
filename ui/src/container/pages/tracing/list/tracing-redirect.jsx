import { PathsEnum } from '@Src/constants';
import { Navigate, useSearchParams } from 'react-router-dom';

const LEGACY_TABS = { tracing: 'requests' };

function TracingRedirect() {
  const [searchParams] = useSearchParams();
  const tab = searchParams.get('tab');

  const nextSearchParams = new URLSearchParams(searchParams);

  if (LEGACY_TABS[tab]) {
    nextSearchParams.set('tab', LEGACY_TABS[tab]);
  }

  return <Navigate replace to={`/${PathsEnum.OBSERVABILITY}?${nextSearchParams.toString()}`} />;
}

export default TracingRedirect;
