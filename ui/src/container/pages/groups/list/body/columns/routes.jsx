import HtmlAnchor from '@Components/html-anchor';
import { PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import {
  Popover,
} from '@radicalbit/radicalbit-design-system';
import { useNavigate } from 'react-router-dom';

function Routes({ routes }) {
  return (
    <Popover content={<PopoverContent routes={routes} />} minWidth="200" title={<strong>Routes</strong>}>
      {routes.length}
    </Popover>
  );
}

function PopoverContent({ routes }) {
  const navigate = useNavigate();

  if (!routes || routes.length === 0) {
    return (
      <div style={{ maxHeight: 200, overflowY: 'auto' }}>
        --
      </div>
    );
  }

  return (
    <div style={{ maxHeight: 200, overflowY: 'auto' }}>
      {routes.map((route) => {
        const handleOnClick = (e) => {
          e.stopPropagation();
          navigate(`/${PathsEnum.ROUTES}/${route.name}?${SEARCH_PARAMS.routes}=${encodeURIComponent(route.name)}&projectUuid=${route.projectUuid}`);
        };

        return (
          <div key={route.uuid}>
            <HtmlAnchor onClick={handleOnClick}>
              {route.name}
            </HtmlAnchor>
          </div>
        );
      })}
    </div>
  );
}

export default Routes;
