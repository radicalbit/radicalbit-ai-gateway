import ConfigStatusTag from '@Container/pages/projects/components/config-status-tag';
import { NewHeader, SectionTitle, Segmented } from '@radicalbit/radicalbit-design-system';

function Header({ activeConfigUuid, configs, onSelectConfig }) {
  const options = configs.map((config) => ({
    value: config.uuid,
    label: (
      <NewHeader
        details={{ one: <ConfigStatusTag config={config} /> }}
        title={(
          <SectionTitle
            size="small"
            title={`Slot ${config.slot}`}
          />
      )}
      />
    ),
  }));

  const handleOnChange = (value) => {
    onSelectConfig(value);
  };

  return (
    <Segmented
      block
      onChange={handleOnChange}
      options={options}
      size="large"
      type="highlighted"
      value={activeConfigUuid}
    />
  );
}

export default Header;
