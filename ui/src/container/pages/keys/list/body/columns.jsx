import HtmlAnchor from '@Components/html-anchor';
import LimitsSummary from '@Components/limits/limits-summary';
import Lucide from '@Components/lucide';
import { useGetThreeDotsMenuItems } from '@Container/pages/keys/three-dots-menu';
import useModals, { modals } from '@Hooks/use-modals';
import {
  CredentialStateEnum, DATE_FORMAT, DATE_FORMAT_SHORT, GATEWAY_OWNER, PathsEnum, ROTATION_FORMAT, RotationStateEnum, SEARCH_PARAMS,
} from '@Src/constants';
import {
  Button,
  DataTableAction,
  Dropdown,
  RelativeDateTime,
  SectionTitle,
  Tooltip,
  Truncate,
} from '@radicalbit/radicalbit-design-system';
import classNames from 'classnames';
import dayjs from 'dayjs';
import { EllipsisVertical } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useRef, useState } from 'react';

const MENU_TRIGGER = ['hover', 'click'];

const EXPIRES_ON_TOOLTIP = 'Expires at end of day (UTC)';

const columns = [
  {
    title: '',
    dataIndex: 'margin-right',
    key: 'margin-right',
    width: '10px',
  },

  {
    title: 'Name',
    dataIndex: 'name',
    key: 'id',
    render: (_, record) => <Name record={record} />,
  },
  {
    title: 'Owner',
    dataIndex: 'owner',
    key: 'owner',
  },
  {
    title: 'Associated Group',
    dataIndex: 'group',
    align: 'center',
    render: (group) => <AssociatedGroup group={group} />,
  },
  {
    title: 'Limits',
    dataIndex: 'limits',
    key: 'limits',
    render: (limits, { uuid }) => <Limits limits={limits} uuid={uuid} />,
  },
  {
    title: 'Created',
    dataIndex: 'createdAt',
    align: 'right',
    sorter: (a, b) => a.createdAt.localeCompare(b.createdAt),
    defaultSortOrder: 'descend',
    render: (date) => <RelativeDateTime format={DATE_FORMAT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
  },
  {
    title: 'Updated',
    dataIndex: 'updatedAt',
    align: 'right',
    key: 'updatedAt',
    render: (date) => <RelativeDateTime format={DATE_FORMAT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
  },
  {
    title: '',
    dataIndex: 'uuid',
    key: 'actions',
    width: '50px',
    render: (uuid, { name }) => <DataTableAction noHide><Actions name={name} uuid={uuid} /></DataTableAction>,
  },
  {
    title: '',
    dataIndex: 'margin-right',
    key: 'margin-right',
    width: '10px',
  },
];

function Name({ record }) {
  const {
    expiresOn, graceEndsAt, lastRotatedAt, name, owner, rotationState, state,
  } = record;
  const className = classNames({ 'line-through': state === CredentialStateEnum.EXPIRED });

  return (
    <SectionTitle
      size="small"
      subtitle={(
        <div className="flex flex-col">
          <ExpiresOn expiresOn={expiresOn} owner={owner} state={state} />

          <Rotation graceEndsAt={graceEndsAt} lastRotatedAt={lastRotatedAt} owner={owner} rotationState={rotationState} />
        </div>
      )}
      title={(
        <Truncate tooltip={{ title: name, placement: 'topLeft' }}>
          <span className={className}>{name}</span>
        </Truncate>
      )}
    />
  );
}

function ExpiresOn({ expiresOn, owner, state }) {
  // Externally managed credentials have no expiry: their lifecycle stays with the identity provider
  if (owner !== GATEWAY_OWNER) {
    return false;
  }

  if (!expiresOn) {
    return 'Never expires';
  }

  // expiresOn is a calendar date: dayjs parses YYYY-MM-DD as a local date, so no timezone shift
  const date = dayjs(expiresOn).format(DATE_FORMAT_SHORT.trim());
  const isExpired = state === CredentialStateEnum.EXPIRED;
  const label = isExpired ? `Expired on ${date}` : `Expires on ${date}`;
  const className = classNames({
    'text-[var(--coo-warning)]': state === CredentialStateEnum.EXPIRING,
    'text-[var(--coo-error)]': isExpired,
  });

  return (
    <Tooltip placement="topLeft" title={EXPIRES_ON_TOOLTIP}>
      <span className={className}>{label}</span>
    </Tooltip>
  );
}

function Rotation({ graceEndsAt, lastRotatedAt, owner, rotationState }) {
  const isGraceEnding = rotationState === RotationStateEnum.GRACE_ENDING;
  const isGraceRunning = rotationState === RotationStateEnum.IN_GRACE || isGraceEnding;
  const className = classNames({ 'text-[var(--coo-warning)]': isGraceEnding });

  // Externally managed credentials are never rotated: their lifecycle stays with the identity provider
  if (owner !== GATEWAY_OWNER) {
    return false;
  }

  if (rotationState === RotationStateEnum.ROTATED) {
    return <span className="text-[var(--coo-success)]">{`Rotated on ${dayjs(lastRotatedAt).format(ROTATION_FORMAT)}`}</span>;
  }

  if (isGraceRunning) {
    return <span className={className}>{`Previous value works until ${dayjs(graceEndsAt).format(ROTATION_FORMAT)}`}</span>;
  }

  return false;
}

function AssociatedGroup({ group }) {
  const navigate = useNavigate();

  const groupName = group?.name;
  const groupUuid = group?.uuid;

  if (groupName) {
    const handleOnClick = (e) => {
      e.stopPropagation();
      navigate(`/${PathsEnum.GROUPS}/${groupUuid}?${SEARCH_PARAMS.groups}=${encodeURIComponent(groupName)}`);
    };

    return (<HtmlAnchor onClick={handleOnClick}>{groupName}</HtmlAnchor>);
  }

  return '--';
}

function Limits({ limits, uuid }) {
  const { showModal } = useModals();

  const handleOnManage = () => {
    showModal(modals.MANAGE_KEY_LIMITS, { uuid });
  };

  return <LimitsSummary limits={limits} onManage={handleOnManage} />;
}

function Actions({ name, uuid }) {
  const buttonRef = useRef(null);

  const [isOpenedByKeyboard, setIsOpenedByKeyboard] = useState(false);

  const items = useGetThreeDotsMenuItems(uuid);

  const handleOnOpenChange = (isOpen) => {
    const { activeElement } = document;
    const isFocusLost = activeElement === document.body || activeElement?.closest('.ant-dropdown');

    if (!isOpen) {
      setIsOpenedByKeyboard(false);
    }

    if (!isOpen && isFocusLost) {
      buttonRef.current?.focus();
    }
  };

  const handleOnKeyDown = (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      setIsOpenedByKeyboard(true);
    }
  };

  const handleOnClick = (e) => {
    e.stopPropagation();
  };

  if (!items.length) {
    return false;
  }

  return (
    <span onClick={handleOnClick} role="presentation">
      <Tooltip title="More actions">
        <Dropdown autoFocus={isOpenedByKeyboard} destroyOnHidden menu={{ items }} onOpenChange={handleOnOpenChange} trigger={MENU_TRIGGER}>
          <Button aria-label={`More actions for ${name}`} onKeyDown={handleOnKeyDown} ref={buttonRef} type="text">
            <Lucide icon={EllipsisVertical} />
          </Button>
        </Dropdown>
      </Tooltip>
    </span>
  );
}

export default columns;
