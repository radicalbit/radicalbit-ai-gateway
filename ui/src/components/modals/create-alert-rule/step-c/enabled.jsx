import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Switch } from '@radicalbit/radicalbit-design-system';

function Enabled() {
  const { form, write } = useFormbitContext();
  const enabled = form?.enabled ?? false;

  const handleOnChange = (checked) => {
    write('enabled', checked);
  };

  const label = enabled ? 'Alert enabled' : 'Alert disabled';

  return (
    <FormField label="Enable alert">
      <div className="flex items-center gap-2">
        <Switch checked={enabled} onChange={handleOnChange} />

        <div>{label}</div>
      </div>
    </FormField>
  );
}

export default Enabled;
