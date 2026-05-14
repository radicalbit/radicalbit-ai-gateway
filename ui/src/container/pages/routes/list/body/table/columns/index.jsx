import { Truncate } from '@radicalbit/radicalbit-design-system';
import dateFormatter from '@Helpers/date-formatter';
import Caching from './caching';
import Errors from './errors';
import Fallbacks from './fallbacks';
import Groups from './groups';
import Guardrails from './guardrails';
import Limits from './limits';
import Models from './models';
import Analytics from './analytics';
import Routing from './routing';

const columns = [
  {
    title: '',
    dataIndex: 'margin-right',
    key: 'margin-right',
    width: '10px',
  },
  {
    title: 'Name',
    dataIndex: 'routeName',
    key: 'routeName',
    width: 250,
    render: (value) => (
      <Truncate tooltip={{ title: value, placement: 'topLeft' }}>
        <span className="font-[var(--coo-font-weight-bold)]">{value}</span>
      </Truncate>
    ),
  },
  {
    title: '',
    dataIndex: 'margin-right',
    key: 'margin-right',
    width: '10px',
  },
  {
    title: 'Groups',
    dataIndex: 'groups',
    align: 'center',
    width: '50px',
    render: (groups = []) => <Groups groups={groups} />,
  },
  {
    title: 'Models',
    dataIndex: 'configuration.chatModels',
    align: 'center',
    width: '100px',
    key: 'configuration.chatModels',
    render: (_, { configuration }) => <Models configuration={configuration} />,
  },
  {
    title: '',
    dataIndex: 'margin-right',
    key: 'margin-right',
    width: '50px',
  },
  {
    title: 'Requests',
    dataIndex: 'metrics.totalRequests',
    align: 'center',
    width: '50px',
    key: 'metrics.totalRequests',
    render: (_, { metrics }) => metrics.totalRequests,
  },
  {
    title: 'Error %',
    dataIndex: 'metrics.errors',
    align: 'center',
    width: '100px',
    key: 'metrics.errors',
    render: (_, { metrics }) => <Errors errors={metrics?.errors} />,
  },
  {
    title: 'Last',
    dataIndex: 'metrics.lastRequestTimestamp',
    key: 'metrics.lastRequestTimestamp',
    align: 'center',
    width: '150px',
    render: (_, { metrics }) => (metrics?.lastRequestTimestamp ? dateFormatter(metrics.lastRequestTimestamp) : '--'),
  },
  {
    title: '',
    dataIndex: 'margin-right',
    key: 'margin-right',
    width: '50px',
  },
  {
    title: 'Adv Routing',
    dataIndex: 'metrics.routing',
    key: 'metrics.routing',
    align: 'center',
    width: '100px',
    render: (_, { metrics: { routing } }) => <div className="flex justify-center"><Routing routing={routing} /></div>,
  },
  {
    title: 'Caching',
    dataIndex: 'metrics.cacheTriggered',
    width: '50px',
    align: 'center',
    key: 'metrics.cacheTriggered',
    render: (_, { metrics, configuration }) => (
      <div className="flex justify-center"><Caching configuration={configuration} metrics={metrics} /></div>
    ),
  },
  {
    title: 'Fallback',
    dataIndex: 'metrics.fallbacks.value',
    key: 'metrics.fallbacks.value',
    align: 'center',
    width: '50px',
    render: (_, { metrics: { fallbacks } }) => <div className="flex justify-center"><Fallbacks fallbacks={fallbacks} /></div>,
  },
  {
    title: 'Guardrails',
    dataIndex: 'metrics.guardrails',
    key: 'metrics.guardrails',
    align: 'center',
    width: '50px',
    render: (_, { metrics: { guardrails } }) => <div className="flex justify-center"><Guardrails guardrails={guardrails} /></div>,
  },
  {
    title: 'Limits',
    dataIndex: 'metrics.rateLimitTriggered',
    key: 'metrics.rateLimitTriggered',
    align: 'center',
    width: '50px',
    render: (_, { metrics, configuration }) => (
      <div className="flex justify-center"><Limits configuration={configuration} metrics={metrics} /></div>
    ),
  },
  {
    title: '',
    dataIndex: 'uuid',
    key: 'actions',
    align: 'center',
    width: '50px',
    render: (_, record) => <Analytics record={record} />,
  },
  {
    title: '',
    dataIndex: 'margin-right',
    key: 'margin-right',
    width: '10px',
  },
];

export default columns;
