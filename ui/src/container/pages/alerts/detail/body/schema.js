import * as yup from 'yup';

const schema = yup.object().shape({
  name: yup.string().required('Name is required'),
  description: yup.string().nullable(),
  project: yup.string().required('Project is required'),
  route: yup.string().required('Route is required'),
  event: yup.string().required('Event is required'),
  recipients: yup.array()
    .of(yup.string())
    .min(1, 'At least one recipient is required')
    .required('At least one recipient is required'),
});

export { schema };
