import { AlertScopeEnum, AlertTimeAggregationEnum } from '@Src/constants';
import * as yup from 'yup';

const schema = yup.object().shape({
  project: yup.string().when('scope', {
    is: AlertScopeEnum.CREDENTIAL,
    then: (field) => field.nullable(),
    otherwise: (field) => field.required('Project is required'),
  }),
  credential: yup.string().when('scope', {
    is: AlertScopeEnum.CREDENTIAL,
    then: (field) => field.required('Credential is required'),
    otherwise: (field) => field.nullable(),
  }),
  scope: yup.string().required('Scope is required'),
  route: yup.string().when('scope', {
    is: AlertScopeEnum.ROUTE,
    then: (field) => field.required('Route is required'),
    otherwise: (field) => field.nullable(),
  }),
  event: yup.string().required('Event is required'),
  timeAggregation: yup.string().required('Time aggregation is required'),
  windowSize: yup.string().when('timeAggregation', {
    is: AlertTimeAggregationEnum.WINDOW,
    then: (field) => field.required('Duration is required'),
    otherwise: (field) => field.nullable(),
  }),
});

const paths = ['scope', 'project', 'credential', 'route', 'event', 'timeAggregation', 'windowSize'];

export { schema, paths };
