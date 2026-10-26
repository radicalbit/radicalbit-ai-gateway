import * as yup from 'yup';
import { CUSTOM_PRESET, GraceModeEnum } from './grace-period';

// The bounds that depend on the credential's expiry are checked in useHandleOnSubmit (getBoundsError)
const schema = yup.object().shape({
  mode: yup.string().oneOf(Object.values(GraceModeEnum)).required(),
  preset: yup.string().required(),
  amount: yup.number().nullable().when(['mode', 'preset'], {
    is: (mode, preset) => mode === GraceModeEnum.GRACE && preset === CUSTOM_PRESET,
    // At least 1 whole unit, so never under 1 hour
    then: (s) => s.typeError('Enter a grace period').integer('Enter whole units').required('Enter a grace period')
      .min(1, 'The grace period must be at least 1 hour'),
  }),
  unit: yup.string().oneOf(['hours', 'days', 'weeks']).required(),
});

export { schema };
