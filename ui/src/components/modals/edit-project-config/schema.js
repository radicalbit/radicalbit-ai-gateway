import * as yup from 'yup';

const schema = yup.object().shape({
  configs: yup.lazy((value) => yup.object(
    Object.keys(value ?? {}).reduce(
      (acc, key) => ({ ...acc, [key]: yup.string().required('Configuration is required') }),
      {},
    ),
  )),
});

export { schema };
