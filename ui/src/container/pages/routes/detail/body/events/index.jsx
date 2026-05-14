import Logo from '@Img/logo.png';
import { useGetEventsByRouteWithRange } from '@Src/store/state/routes/vertical-hooks';
import {
  Board, Button, Collapse, Skeleton, Void,
} from '@radicalbit/radicalbit-design-system';
import { useParams } from 'react-router-dom';
import Caching from './items/caching';
import useGetCachingItem from './items/caching/use-get-caching-items';
import Fallbacks from './items/fallbacks';
import useGetFallbacksItem from './items/fallbacks/use-get-fallbacks-items';
import Guardrails from './items/guardrails';
import useGetGuardrailsItem from './items/guardrails/use-get-guardrails-items';
import RateLimiting from './items/rate-limiting';
import useGetRateLimitingItem from './items/rate-limiting/use-get-rate-limiting-items';
import TokensLimiting from './items/tokens-limiting';
import useGetTokensLimitingItem from './items/tokens-limiting/use-get-tokens-limiting-items';

function Events() {
  const { name } = useParams();

  const { isLoading, isError, isSuccess, refetch } = useGetEventsByRouteWithRange(name);

  const cachingItem = useGetCachingItem();
  const fallbackItem = useGetFallbacksItem();
  const guardrailItem = useGetGuardrailsItem();
  const rateLimitingItem = useGetRateLimitingItem();
  const tokenLimitingItem = useGetTokensLimitingItem();

  if (isLoading) {
    return <IsLoading />;
  }

  if (isError) {
    return <IsError refetch={refetch} />;
  }

  if (!isSuccess) {
    return false;
  }

  const items = [
    {
      key: 1,
      children: <Caching />,
      ...cachingItem,
    },
    {
      key: 2,
      children: <Fallbacks />,
      ...fallbackItem,
    },
    {
      key: 3,
      children: <Guardrails />,
      ...guardrailItem,
    },
    {
      key: 4,
      children: <RateLimiting />,
      ...rateLimitingItem,
    },
    {
      key: 5,
      children: <TokensLimiting />,
      ...tokenLimitingItem,
    },
  ];

  return (
    <Collapse
      key={name}
      expandIconPosition="right"
      items={items}
      type="border-bottom"
    />
  );
}

function IsLoading() {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton.Input
        active
        className="flex-1"
        style={{
          height: 160,
          width: '100%',
          borderRadius: 8,
        }}
      />

      <Skeleton.Input
        active
        style={{
          height: 160,
          width: '100%',
          borderRadius: 8,
        }}
      />
    </div>
  );
}

function IsError({ refetch }) {
  return (
    <Board
      main={(
        <Void
          actions={<Button onClick={refetch}>Retry</Button>}
          description={(
            <>
              This might be temporary
              <br />
              please retry later
            </>
          )}
          image={<img alt="Logo" src={Logo} />}
          style={{ height: '80vh' }}
          title="Unable to load Route"
        />
      )}
    />
  );
}

export default Events;
