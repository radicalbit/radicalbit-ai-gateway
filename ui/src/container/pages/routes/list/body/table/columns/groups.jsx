import HtmlAnchor from '@Components/html-anchor';
import { PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import {
  Popover,
} from '@radicalbit/radicalbit-design-system';
import { useNavigate } from 'react-router-dom';

function Groups({ groups }) {
  return (
    <Popover content={<PopoverContent groups={groups} />} minWidth="200" title={<strong>Groups</strong>}>
      {groups.length}
    </Popover>
  );
}

function PopoverContent({ groups }) {
  const navigate = useNavigate();

  if (!groups || groups.length === 0) {
    return (
      <div style={{ maxHeight: 200, overflowY: 'auto' }}>
        --
      </div>
    );
  }

  return (
    <div style={{ maxHeight: 200, overflowY: 'auto' }}>
      {groups.map((group) => {
        const handleOnClick = (e) => {
          e.stopPropagation();
          navigate(`/${PathsEnum.GROUPS}/${group.uuid}?${SEARCH_PARAMS.groups}=${encodeURIComponent(group.name)}`);
        };

        return (
          <div key={group.uuid}>
            <HtmlAnchor onClick={handleOnClick}>
              {group.name}
            </HtmlAnchor>
          </div>
        );
      })}
    </div>
  );
}

export default Groups;
