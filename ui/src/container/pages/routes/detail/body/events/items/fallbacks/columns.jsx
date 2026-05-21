import dateFormatter from '@Helpers/date-formatter';
import dayjs from 'dayjs';
// import HtmlAnchor from '@Components/html-anchor';
// import { PathsEnum } from '@Src/constants';
// import { Tooltip } from '@radicalbit/radicalbit-design-system';
// import { useNavigate } from 'react-router-dom';

const columns = [
  {
    title: 'Timestamp',
    dataIndex: 'timestamp',
    key: 'timestamp',
    sorter: (a, b) => dayjs(a.timestamp).unix() - dayjs(b.timestamp).unix(),
    render: (value) => dateFormatter(value),
  },
  {
    title: 'Target Model',
    dataIndex: 'target',
    key: 'target',
    render: (value) => value || '--',
  },
  {
    title: 'Fallback Model',
    dataIndex: 'fallback',
    key: 'fallback',
    render: (value) => value || '--',
  },
  // {
  //   title: 'Credential Name',
  //   dataIndex: 'apiKeyName',
  //   key: 'apiKeyName',
  //   align: 'left',
  //   ellipsis: true,
  // },
];

// function GoToKey({ apiKeyName, apiKeyUuid }) {
//   const navigate = useNavigate();

//   const handleOnClick = (e) => {
//     e.stopPropagation();
//     navigate(`/${PathsEnum.CREDENTIALS}/${apiKeyUuid}`);
//   };

//   return <HtmlAnchor onClick={handleOnClick}>{apiKeyName}</HtmlAnchor>;
// }

export default columns;
