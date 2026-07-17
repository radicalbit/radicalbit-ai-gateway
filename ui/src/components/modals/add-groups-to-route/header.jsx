import HtmlAnchor from '@Components/html-anchor';
import Lucide from '@Components/lucide';
import useModals from '@Hooks/use-modals';
import { PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import { useGetRouteByNameWithRange } from '@Src/store/state/routes/vertical-hooks';
import {
  Popover,
  SectionTitle,
  Skeleton,
} from '@radicalbit/radicalbit-design-system';
import { Info } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

function Header() {
  const { modalPayload } = useModals();
  const name = modalPayload?.data?.name;

  return (
    <SectionTitle
      subtitle={(
        <div className="flex flex-col">
          <div>You can select one or many groups to associate to:</div>

          <strong>{name}</strong>

          <AssociatedGroups />
        </div>
      )}
      title="Associate groups"
      titleColor="primary"
    />
  );
}

function AssociatedGroups() {
  const navigate = useNavigate();
  const { modalPayload } = useModals();
  const name = modalPayload?.data?.name;

  const { data, isLoading, isError, isSuccess } = useGetRouteByNameWithRange(name, { skip: !name });
  const groups = data?.groups || [];
  const associated = groups.map((i) => ({ label: i.name, value: i.uuid }));

  if (isLoading) {
    return <Skeleton.Input active />;
  }

  if (isError) {
    return 'Something went wrong';
  }

  if (!isSuccess) {
    return false;
  }

  const popoverContent = (
    <div>
      <strong>Groups already associated</strong>

      <div style={{ maxHeight: 200, overflowY: 'auto' }}>
        {associated.map(({ label, value }) => {
          const handleOnClick = () => {
            navigate(`/${PathsEnum.GROUPS}/${value}?${SEARCH_PARAMS.groups}=${encodeURIComponent(label)}`);
          };

          return (
            <div key={value}>
              <HtmlAnchor onClick={handleOnClick}>
                {label}
              </HtmlAnchor>
            </div>
          );
        })}
      </div>
    </div>
  );

  if (associated.length === 0) {
    return <span>{`Groups already associated: ${associated.length}`}</span>;
  }

  return (
    <div className="flex flex-row items-center gap-2">
      <span>{`Groups already associated: ${associated.length}`}</span>

      <Popover content={popoverContent}>
        <Lucide icon={Info} />
      </Popover>
    </div>
  );
}

export default Header;
