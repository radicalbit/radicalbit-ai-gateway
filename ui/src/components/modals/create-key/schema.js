import * as yup from 'yup';

const ExpiryModeEnum = {
  NEVER: 'never',
  DATE: 'date',
};

const schema = yup.object().shape({
  name: yup.string()
    .max(30, 'ID max length is 30 characters')
    .matches(/^[A-Za-z0-9_\\-]+$/, 'ID can be filled only with letters, numbers, underscores and dashes')
    .matches(/^[A-Za-z]/, 'ID must start with a letter')
    .required('ID is required'),
  expiryMode: yup.string().oneOf(Object.values(ExpiryModeEnum)).required(),
  // A calendar date (YYYY-MM-DD), required only when the credential expires
  expiresOn: yup.string().nullable().when('expiryMode', {
    is: ExpiryModeEnum.DATE,
    then: (s) => s.required('Select an expiry date'),
  }),
});

const initialValues = { expiryMode: ExpiryModeEnum.NEVER, expiresOn: null };

export { ExpiryModeEnum, initialValues, schema };
