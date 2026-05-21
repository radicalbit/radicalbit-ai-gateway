import Deepview from './deepview';
import Actions from './actions';
import Utilities from './utilities';

function RoutesSecondaryColumn() {
  return (
    <div className="flex flex-col gap-8 p-4">
      <Actions />

      <Utilities />

      <Deepview />
    </div>
  );
}

export default RoutesSecondaryColumn;
