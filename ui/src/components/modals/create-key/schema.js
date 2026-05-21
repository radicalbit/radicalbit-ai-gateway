import * as yup from 'yup';

const schema = yup.object().shape({
  name: yup.string()
    .max(30, 'ID max length is 30 characters')
    .matches(/^[A-Za-z0-9_\\-]+$/, 'ID can be filled only with letters, numbers, underscores and dashes')
    .matches(/^[A-Za-z]/, 'ID must start with a letter')
    .required('ID is required'),
});

export { schema };
