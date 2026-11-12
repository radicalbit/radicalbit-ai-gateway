import HtmlAnchor from '@Components/html-anchor';
import { PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import { useNavigate } from 'react-router-dom';

function CredentialLink({ apiKeyName }) {
  const navigate = useNavigate();

  const handleOnClick = (e) => {
    e.stopPropagation();
    navigate(`/${PathsEnum.CREDENTIALS}?${SEARCH_PARAMS.credentials}=${encodeURIComponent(apiKeyName)}`);
  };

  if (!apiKeyName) {
    return '--';
  }

  return <HtmlAnchor onClick={handleOnClick}>{apiKeyName}</HtmlAnchor>;
}

function GroupLink({ groupName, groupUuid }) {
  const navigate = useNavigate();

  const handleOnClick = (e) => {
    e.stopPropagation();
    navigate(`/${PathsEnum.GROUPS}/${groupUuid}?${SEARCH_PARAMS.groups}=${encodeURIComponent(groupName)}`);
  };

  if (!groupName || !groupUuid) {
    return '--';
  }

  return <HtmlAnchor onClick={handleOnClick}>{groupName}</HtmlAnchor>;
}

export { CredentialLink, GroupLink };
