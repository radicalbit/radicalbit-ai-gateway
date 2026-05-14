import HtmlAnchor from '@Components/html-anchor';
import { PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import { useNavigate } from 'react-router-dom';

function GoToKey({ apiKeyName }) {
  const navigate = useNavigate();

  const handleOnClick = (e) => {
    e.stopPropagation();
    navigate(`/${PathsEnum.CREDENTIALS}?${SEARCH_PARAMS.credentials}=${encodeURIComponent(apiKeyName)}`);
  };

  return <HtmlAnchor onClick={handleOnClick}>{apiKeyName}</HtmlAnchor>;
}

export default GoToKey;
