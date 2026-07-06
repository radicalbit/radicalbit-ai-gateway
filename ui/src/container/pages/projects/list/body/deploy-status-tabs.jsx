import { ProjectStatusEnum } from '@Src/constants';
import { Board, Button } from '@radicalbit/radicalbit-design-system';
import { useSearchParams } from 'react-router-dom';

const DEPLOY_STATUS_QP = 'deployStatus';

const DEPLOY_STATUS_ALL = 'all';

const DEPLOY_STATUS_TABS = [
  { key: DEPLOY_STATUS_ALL, label: 'All' },
  { key: ProjectStatusEnum.DEV, label: 'Dev' },
  { key: ProjectStatusEnum.PROD, label: 'Prod' },
];

function DeployStatusTabs() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeStatus = searchParams.get(DEPLOY_STATUS_QP) || DEPLOY_STATUS_ALL;

  const handleOnSelect = (status) => {
    setSearchParams((prev) => {
      if (status === DEPLOY_STATUS_ALL) {
        prev.delete(DEPLOY_STATUS_QP);
      } else {
        prev.set(DEPLOY_STATUS_QP, status);
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
          {DEPLOY_STATUS_TABS.map(({ key, label }) => {
            const handleOnClick = () => {
              handleOnSelect(key);
            };

            return (
              <Button
                key={key}
                onClick={handleOnClick}
                type={activeStatus === key ? 'primary' : 'text'}
              >
                {label}
              </Button>
            );
          })}
        </div>
      )}
      size="xsmall"
    />
  );
}

export { DEPLOY_STATUS_QP, DEPLOY_STATUS_ALL };
export default DeployStatusTabs;
