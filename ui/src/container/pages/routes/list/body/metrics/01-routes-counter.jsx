import { numberFormatterInt } from '@Src/constants';
import { useGetRoutesWithRange } from '@Src/store/state/routes/vertical-hooks';
import {
  Board,
  NewHeader,
} from '@radicalbit/radicalbit-design-system';
import CounterSkeleton from './counter-skeleton';

function RoutesCounter() {
  const { data = [], isLoading, isSuccess } = useGetRoutesWithRange();
  const count = data?.length;

  if (isLoading) {
    return <CounterSkeleton />;
  }

  if (!isSuccess) {
    return false;
  }

  return (
    <Board
      className="flex-1"
      header={<NewHeader title="Routes" />}
      main={<h2>{numberFormatterInt(count)}</h2>}
      type="primary-light"
    />
  );
}

export default RoutesCounter;
