import HtmlAnchor from '@Components/html-anchor';
import Lucide from '@Components/lucide';
import useModals from '@Hooks/use-modals';
import { PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import { useGetGroupQuery } from '@State/groups/api';
import {
  Popover,
  SectionTitle,
  Skeleton,
} from '@radicalbit/radicalbit-design-system';
import { Info } from 'lucide-react';
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
          <div>You can select one or many credentials to associate to:</div>

          <strong>{name}</strong>

          <AssociatedKeys />
        </div>
      )}
      title="Associate credentials"
      titleColor="primary"
    />
  );
}

function AssociatedKeys() {
  const { modalPayload } = useModals();
  const navigate = useNavigate();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetGroupQuery(uuid, { skip: !uuid });
  const keys = data?.keys || [];
  const associated = keys.map((i) => ({ label: i.name, value: i.uuid }));

  const popoverContent = (
    <div>
      <strong>Credentials already associated</strong>

      <div style={{ maxHeight: 200, overflowY: 'auto' }}>
        {associated.map(({ label, value }) => {
          const handleOnClick = () => {
            navigate(`/${PathsEnum.CREDENTIALS}?${SEARCH_PARAMS.credentials}=${encodeURIComponent(label)}`);
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
    return <span>{`Credentials already associated: ${associated.length}`}</span>;
  }

  return (
    <div className="flex flex-row items-center gap-2">
      <span>{`Credentials already associated: ${associated.length}`}</span>

      <Popover content={popoverContent}>
        <Lucide icon={Info} />
      </Popover>
    </div>
  );
}

export default Header;
