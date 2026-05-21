import * as yup from 'yup';

const schema = yup.object().shape({
  name: yup.string()
    .max(30, 'Name max length is 30 characters')
    .matches(/^[A-Za-z0-9_\\-]+$/, 'Name can be filled only with letters, numbers, underscores and dashes')
    .matches(/^[A-Za-z]/, 'Name must start with a letter')
    .required('Name is required'),
  description: yup.string()
    .max(200, 'Description max length is 200 characters')
    .optional(),
});

export { schema };
