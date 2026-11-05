import useModals, { modals } from '@Hooks/use-modals';
import { formatCount } from '@Components/limits/helpers';
import { useGetProjectBudgetQuery } from '@State/projects/api';
import { Alert, Button } from '@radicalbit/radicalbit-design-system';
import { Fragment } from 'react';
import { ConflictAlertTypeEnum, getConflictAlertType } from './helpers';

function Conflicts() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetProjectBudgetQuery(uuid, { skip: !uuid });
  const alertType = getConflictAlertType(data?.routeBudgets);

  if (alertType === ConflictAlertTypeEnum.PUBLISHED) {
    return <PublishedConflict />;
  }

  if (alertType === ConflictAlertTypeEnum.DRAFT) {
    return <DraftConflicts />;
  }

  return false;
}

function PublishedConflict() {
  const { modalPayload, showModal } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetProjectBudgetQuery(uuid, { skip: !uuid });
  const published = data?.routeBudgets?.published ?? [];
  const budgetRouting = data?.routeBudgets?.budgetRouting ?? [];
  const servedConfigUuid = data?.servedConfigUuid;

  const handleOnOpenConfiguration = () => {
    showModal(modals.EDIT_PROJECT_CONFIG, { uuid, activeConfigUuid: servedConfigUuid });
  };

  const routingByBudget = published.filter((route) => budgetRouting.includes(route));
  const title = `${formatCount(published.length, 'published route')} ${published.length === 1 ? 'has its' : 'have their'} own budget`;

  return (
    <Alert
      description={(
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <span>
              A project budget and route budgets exclude each other. Remove budget_limiting from
              {' '}

              <RouteNames routes={published} />

              {' '}
              of the published configuration, then add the project budget.
            </span>

            <BudgetRouting routes={routingByBudget} />
          </div>

          <div>
            <Button onClick={handleOnOpenConfiguration} size="small" type="primary">Open configuration</Button>
          </div>
        </div>
      )}
      showIcon
      title={title}
      type={ConflictAlertTypeEnum.PUBLISHED}
    />
  );
}

function DraftConflicts() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetProjectBudgetQuery(uuid, { skip: !uuid });
  const draftConfigs = data?.routeBudgets?.draftConfigs ?? [];

  return (
    <div className="flex flex-col gap-2">
      {draftConfigs.map((draftConfig) => <DraftConflict key={draftConfig.configUuid} draftConfig={draftConfig} />)}
    </div>
  );
}

function DraftConflict({ draftConfig }) {
  const { modalPayload, showModal } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { configUuid, routes, slot } = draftConfig;

  const handleOnOpenConfiguration = () => {
    showModal(modals.EDIT_PROJECT_CONFIG, { uuid, activeConfigUuid: configUuid });
  };

  const verb = routes.length === 1 ? 'declares' : 'declare';
  const title = `Slot ${slot} (draft) has routes with their own budget`;

  return (
    <Alert
      description={(
        <div className="flex flex-col gap-4">
          <span>
            A draft can&apos;t be published while
            {' '}

            <RouteNames routes={routes} />

            {' '}

            {verb}

            {' '}
            budget_limiting and the project has a budget.
          </span>

          <div>
            <Button onClick={handleOnOpenConfiguration} size="small" type="primary">Open configuration</Button>
          </div>
        </div>
      )}
      showIcon
      title={title}
      type={ConflictAlertTypeEnum.DRAFT}
    />
  );
}

function BudgetRouting({ routes }) {
  if (!routes.length) {
    return false;
  }

  const verb = routes.length === 1 ? 'picks its' : 'pick their';

  return (
    <span>
      <RouteNames routes={routes} />

      {' '}

      {`also ${verb} model by budget, which needs a budget on the route.`}
    </span>
  );
}

function RouteNames({ routes }) {
  const names = routes.map((route, index) => (
    <Fragment key={route}>
      {index > 0 ? ', ' : false}

      <code className="whitespace-nowrap">{route}</code>
    </Fragment>
  ));

  return <>{names}</>;
}

export default Conflicts;
