import { Skeleton } from '@radicalbit/radicalbit-design-system';

function CounterSkeleton() {
  return (
    <Skeleton.Input
      active
      block
      className="flex-1"
      style={{
        borderRadius: 8,
        height: '12rem',
      }}
    />
  );
}

export default CounterSkeleton;
