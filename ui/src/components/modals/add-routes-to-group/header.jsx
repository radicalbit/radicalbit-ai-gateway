import { faCircleInfo } from '@fortawesome/free-solid-svg-icons';
import HtmlAnchor from '@Components/html-anchor';
import useModals from '@Hooks/use-modals';
import { PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import { useGetGroupQuery } from '@State/groups/api';
import {
  FontAwesomeIcon,
  Popover,
  SectionTitle,
  Skeleton,
} from '@radicalbit/radicalbit-design-system';
import { useNavigate } from 'react-router-dom';

function Header() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data, isError, isLoading, isSuccess } = useGetGroupQuery(uuid, { skip: !uuid });
  const name = data?.name;

  if (isLoading) {
    return <Skeleton.Input active />;
  }

  if (isError) {
    return 'Something went wrong';
  }

  if (!isSuccess) {
    return false;
  }

  return (
    <SectionTitle
      subtitle={(
        <div className="flex flex-col">
          <div>You can select one or many routes to associate to:</div>

          <strong>{name}</strong>

          <AssociatedRoutes />
        </div>
      )}
      title="Associate routes"
      titleColor="primary"
    />
  );
}

function AssociatedRoutes() {
  const { modalPayload } = useModals();
  const navigate = useNavigate();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetGroupQuery(uuid, { skip: !uuid });
  const routes = data?.routes || [];

  const popoverContent = (
    <div>
      <strong>Routes already associated</strong>

      <div style={{ maxHeight: 200, overflowY: 'auto' }}>
        {routes.map(({ name, projectUuid }) => {
          const handleOnClick = () => {
            navigate(`/${PathsEnum.ROUTES}/${name}?${SEARCH_PARAMS.routes}=${name}&projectUuid=${projectUuid}`);
          };

          return (
            <div key={name}>
              <HtmlAnchor onClick={handleOnClick}>
                {name}
              </HtmlAnchor>
            </div>
          );
        })}
      </div>
    </div>
  );

  if (routes.length === 0) {
    return <span>{`Routes already associated: ${routes.length}`}</span>;
  }

  return (
    <div className="flex flex-row items-center gap-2">
      <span>{`Routes already associated: ${routes.length}`}</span>

      <Popover content={popoverContent}>
        <FontAwesomeIcon icon={faCircleInfo} />
      </Popover>
    </div>
  );
}

export default Header;
