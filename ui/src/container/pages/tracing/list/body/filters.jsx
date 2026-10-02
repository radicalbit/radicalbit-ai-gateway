import TagsFilter from '@Components/tags-filter';
import CustomRange from '@Components/time-filter/custom-range';
import { FormField } from '@radicalbit/radicalbit-design-system';
import { useId } from 'react';
import { useSearchParams } from 'react-router-dom';
import ProjectFilter from './project-filter';
import RequestTypeFilter from './request-type-filter';
import RoutesFilter from './routes-filter';

function Filters() {
  const projectId = useId();
  const tagsId = useId();
  const requestTypeId = useId();
  const routesId = useId();
  const timeRangeId = useId();

  const [searchParams] = useSearchParams();
  const isTracingTab = searchParams.get('tab') === 'tracing';

  return (
    <div className="flex flex-row flex-wrap items-end gap-4">
      <FormField htmlFor={projectId} label="Project">
        <ProjectFilter id={projectId} />
      </FormField>

      <FormField htmlFor={tagsId} label="Tags">
        <TagsFilter id={tagsId} />
      </FormField>

      {isTracingTab && (
        <FormField htmlFor={requestTypeId} label="Type">
          <RequestTypeFilter id={requestTypeId} />
        </FormField>
      )}

      <FormField htmlFor={routesId} label="Routes">
        <RoutesFilter id={routesId} />
      </FormField>

      <FormField htmlFor={timeRangeId} label="Time range">
        <CustomRange id={timeRangeId} />
      </FormField>
    </div>
  );
}

export default Filters;
