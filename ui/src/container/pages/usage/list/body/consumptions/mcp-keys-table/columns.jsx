import HtmlAnchor from '@Components/html-anchor';
import { PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import {
  formatInt,
  formatText,
  formatTimestamp,
} from '@Src/helpers/column-formatters';
import { useNavigate } from 'react-router-dom';

function AssociatedGroup({ groupName, groupUuid }) {
  const navigate = useNavigate();

  if (groupName) {
    const handleOnClick = (e) => {
      e.stopPropagation();
      navigate(`/${PathsEnum.GROUPS}/${groupUuid}?${SEARCH_PARAMS.groups}=${encodeURIComponent(groupName)}`);
    };

    return (<HtmlAnchor onClick={handleOnClick}>{groupName}</HtmlAnchor>);
  }

  return '--';
}

const columns = [
  {
    title: 'Credential',
    dataIndex: 'keyName',
    align: 'left',
    render: formatText,
  },
  {
    title: 'Group',
    dataIndex: 'groupName',
    align: 'left',
    render: (groupName, record) => <AssociatedGroup groupName={groupName} groupUuid={record.groupUuid} />,
  },
  {
    title: 'Invocations',
    dataIndex: 'counter',
    align: 'right',
    render: formatInt,
  },
  {
    title: 'Last Call',
    dataIndex: 'lastCall',
    align: 'right',
    render: formatTimestamp,
  },
];

export default columns;
