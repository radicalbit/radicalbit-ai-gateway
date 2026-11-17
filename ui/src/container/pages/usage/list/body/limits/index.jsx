import { FormField } from '@radicalbit/radicalbit-design-system';
import { useId } from 'react';
import ProjectFilter from '../project-filter';
import RoutesFilter from '../routes-filter';
import LimitStatusFilter from './limit-status-filter';
import ProjectBudget from './project-budget';
import Routes from './routes';

function Limits() {
  const projectId = useId();
  const statusId = useId();
  const routesId = useId();

  return (
    <div className="flex flex-col gap-8 h-full p-4">
      <div className="flex flex-col gap-4">
        <div className="flex flex-row items-center gap-4">
          <FormField htmlFor={projectId} label="Project">
            <ProjectFilter id={projectId} />
          </FormField>

          <FormField htmlFor={statusId} label="Limit status">
            <LimitStatusFilter id={statusId} />
          </FormField>
        </div>

        <ProjectBudget />
      </div>

      <div className="flex flex-col gap-4">
        <div className="flex flex-row items-center gap-4">
          <FormField htmlFor={routesId} label="Routes">
            <RoutesFilter id={routesId} />
          </FormField>
        </div>

        <Routes />
      </div>
    </div>
  );
}

export default Limits;
