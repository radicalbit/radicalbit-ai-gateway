import HtmlAnchor from '@Components/html-anchor';
import { PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import {
  Popover,
} from '@radicalbit/radicalbit-design-system';
import { useNavigate } from 'react-router-dom';

function Keys({ keys }) {
  return (
    <Popover content={<PopoverContent keys={keys} />} minWidth="200" title={<strong>Credentials</strong>}>
      {keys.length}
    </Popover>
  );
}

function PopoverContent({ keys }) {
  const navigate = useNavigate();

  if (!keys || keys.length === 0) {
    return (
      <div style={{ maxHeight: 200, overflowY: 'auto' }}>
        --
      </div>
    );
  }

  return (
    <div style={{ maxHeight: 200, overflowY: 'auto' }}>
      {keys.map((key) => {
        const handleOnClick = (e) => {
          e.stopPropagation();
          navigate(`/${PathsEnum.CREDENTIALS}?${SEARCH_PARAMS.credentials}=${encodeURIComponent(key.name)}`);
        };

        return (
          <div key={key.uuid}>
            <HtmlAnchor onClick={handleOnClick}>
              {key.name}
            </HtmlAnchor>
          </div>
        );
      })}
    </div>
  );
}

export default Keys;
