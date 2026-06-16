import ConfigStatusTag from '@Container/pages/projects/components/config-status-tag';
import {
  Board, NewHeader, SectionTitle,
} from '@radicalbit/radicalbit-design-system';

function Header({ activeConfigUuid, configs, onSelectConfig }) {
  const slots = configs.map((config) => {
    const active = config.uuid === activeConfigUuid;

    return (
      <HeaderSlot
        key={config.uuid}
        active={active}
        config={config}
        onSelectConfig={onSelectConfig}
      />
    );
  });

  return <div className="flex gap-2">{slots}</div>;
}

function HeaderSlot({ active, config, onSelectConfig }) {
  const boardType = active ? 'primary-light' : undefined;
  const cursorPointer = !active ? 'cursor-pointer' : '';

  const handleOnSelect = () => {
    onSelectConfig(config.uuid);
  };

  return (
    <div className={`flex-1 ${cursorPointer}`} onClick={handleOnSelect}>
      <Board
        main={(
          <NewHeader
            details={{ one: <ConfigStatusTag configStatus={config.configStatus} /> }}
            title={<SectionTitle size="small" title={`Slot ${config.slot}`} />}
          />
        )}
        size="xsmall"
        type={boardType}
      />
    </div>
  );
}

export default Header;
