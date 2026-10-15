import { AlertTimeAggregationEnum } from '@Src/constants';
import * as yup from 'yup';

const schema = yup.object().shape({
  project: yup.string().required('Project is required'),
  route: yup.string().required('Route is required'),
  event: yup.string().required('Event is required'),
  timeAggregation: yup.string().required('Time aggregation is required'),
  windowSize: yup.string().when('timeAggregation', {
    is: AlertTimeAggregationEnum.WINDOW,
    then: (field) => field.required('Duration is required'),
    otherwise: (field) => field.nullable(),
  }),
});

const paths = ['project', 'route', 'event', 'timeAggregation', 'windowSize'];

export { schema, paths };
