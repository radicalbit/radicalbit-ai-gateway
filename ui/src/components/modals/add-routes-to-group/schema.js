import * as yup from 'yup';

const schema = yup.object().shape({
  projectUuid: yup
    .string()
    .required('Project is required'),
  routes: yup
    .array()
    .of(
      yup
        .string()
        .required('Name is required'),
    )
    .min(1, 'At least one route is required')
    .required('Routes is required'),
});

export { schema };
