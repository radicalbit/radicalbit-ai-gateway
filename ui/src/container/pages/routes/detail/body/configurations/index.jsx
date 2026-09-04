import Logo from '@Img/logo.png';
import { useGetRouteByNameWithRange } from '@Src/store/state/routes/vertical-hooks';
import {
  Board,
  Button,
  Collapse,
  Skeleton,
  Void,
} from '@radicalbit/radicalbit-design-system';
import { useParams } from 'react-router-dom';
import {
  AdvancedRouting,
  Cache,
  DurationLimiting,
  Fallback,
  Guardrails,
  Models,
  RateLimiting,
  TokenLimit,
  useGetAdvancedRoutingItem,
  useGetCacheItem,
  useGetDurationLimitingItem,
  useGetFallbackItem,
  useGetGuardrailsItem,
  useGetModelItem,
  useGetRateLimitingItem,
  useGetTokenLimitingItem,
} from './items';

function Configurations() {
  const { name } = useParams();

  const modelItems = useGetModelItem();
  const fallbackItem = useGetFallbackItem();
  const guardrailItem = useGetGuardrailsItem();
  const rateLimitingItem = useGetRateLimitingItem();
  const tokenLimitingItem = useGetTokenLimitingItem();
  const durationLimitingItem = useGetDurationLimitingItem();
  const cacheItem = useGetCacheItem();
  const advancedRoutingItem = useGetAdvancedRoutingItem();

  const { isLoading, isError, isSuccess, refetch } = useGetRouteByNameWithRange(name);

  if (isLoading) {
    return <IsLoading />;
  }

  if (isError) {
    return <IsError refetch={refetch} />;
  }

  if (!isSuccess) {
    return false;
  }

  const itemsOne = [
    {
      key: 1,
      children: <Models />,
      ...modelItems,
    },
    {
      key: 2,
      children: <AdvancedRouting />,
      ...advancedRoutingItem,
    },
    {
      key: 3,
      children: <Cache />,
      ...cacheItem,
    },
  ];

  const itemsTwo = [
    {
      key: 3,
      children: <Fallback />,
      ...fallbackItem,
    },
    {
      key: 4,
      children: <Guardrails />,
      ...guardrailItem,
    },
    {
      key: 5,
      children: <RateLimiting />,
      ...rateLimitingItem,
    },
    {
      key: 6,
      children: <TokenLimit />,
      ...tokenLimitingItem,
    },
    {
      key: 7,
      children: <DurationLimiting />,
      ...durationLimitingItem,
    },
  ];

  return (
    // needed to re-render the collapse
    <div key={name} className="flex flex-col px-2 py-4">
      <Collapse
        expandIconPosition="right"
        items={itemsOne}
        type="border-bottom"
      />

      <Collapse
        expandIconPosition="right"
        items={itemsTwo}
        type="border-bottom"
      />
    </div>
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

export default Configurations;
