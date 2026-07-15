import * as yup from 'yup';

const schema = yup.object().shape({
  project: yup.string().required('Project is required'),
  route: yup.string().required('Route is required'),
  event: yup.string().required('Event is required'),
});

const paths = ['project', 'route', 'event'];

export { schema, paths };
