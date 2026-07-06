import { CONFIG_LIST_FILTER_LABELS, ConfigListFilterEnum } from '@Src/constants';
import { Board, Button } from '@radicalbit/radicalbit-design-system';
import { useSearchParams } from 'react-router-dom';

const STATUS_QP = 'status';

function StatusTabs() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeStatus = searchParams.get(STATUS_QP) || ConfigListFilterEnum.ALL;

  const handleOnSelect = (status) => {
    setSearchParams((prev) => {
      if (status === ConfigListFilterEnum.ALL) {
        prev.delete(STATUS_QP);
      } else {
        prev.set(STATUS_QP, status);
      }
      return prev;
    });
  };

  return (
    <Board
      height="100%"
      modifier="justify-center"
      secondary={(
        <div className="flex gap-2">
          {Object.values(ConfigListFilterEnum).map((status) => {
            const handleOnClick = () => {
              handleOnSelect(status);
            };

            return (
              <Button
                key={status}
                onClick={handleOnClick}
                type={activeStatus === status ? 'primary' : 'text'}
              >
                {CONFIG_LIST_FILTER_LABELS[status]}
              </Button>
            );
          })}
        </div>
      )}
      size="xsmall"
    />
  );
}

export { STATUS_QP };
export default StatusTabs;
