import * as yup from 'yup';

const NAME_REGEX = /^[A-Za-z0-9 _\-#.]+$/;

const schema = yup.object().shape({
  name: yup.string()
    .min(3, 'Name min length is 3 characters')
    .max(60, 'Name max length is 60 characters')
    .matches(NAME_REGEX, 'Name can be filled only with letters, numbers, spaces and the characters _ - # .')
    .required('Name is required'),
  description: yup.string()
    .max(200, 'Description max length is 200 characters')
    .test('min-length', 'Description min length is 3 characters', (value) => !value || value.length >= 3)
    .nullable(),
  project: yup.string().required('Project is required'),
  route: yup.string().required('Route is required'),
  event: yup.string().required('Event is required'),
  recipients: yup.array()
    .of(yup.string())
    .min(1, 'At least one recipient is required')
    .required('At least one recipient is required'),
});

export { schema };
