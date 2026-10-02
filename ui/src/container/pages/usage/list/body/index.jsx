import Lucide from '@Components/lucide';
import { WIDE_MAIN_LAYOUT_CONFIGURATION } from '@Container/layout/layout-provider/layout-provider-configuration';
import usePersistProjectUuid from '@Hooks/use-persist-project-uuid';
import { Tabs, Void } from '@radicalbit/radicalbit-design-system';
import { FolderOpen } from 'lucide-react';
import { useEffect, useId } from 'react';
import { useDispatch } from 'react-redux';
import { useSearchParams } from 'react-router-dom';
import Consumptions from './consumptions';
import Limits from './limits';
import ProjectFilter from './project-filter';

const USAGE_TABS = {
  consumptions: {
    key: 'consumptions',
    label: 'Consumptions',
  },
  limits: {
    key: 'limits',
    label: 'Limits',
  },
};

function Body() {
  useInitLayoutConfigurations();

  usePersistProjectUuid();

  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  if (!projectUuid) {
    return <NoProjectSelected />;
  }

  return <ProjectSelected />;
}

function NoProjectSelected() {
  const projectId = useId();

  return (
    <div className="flex justify-center items-center h-full">
      <Void
        actions={<ProjectFilter id={projectId} />}
        description="Select a project to view usage data"
        image={<Lucide icon={FolderOpen} />}
        title="No project selected"
      />
    </div>
  );
}

function ProjectSelected() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get('usageTab');

  const handleOnChange = (value) => {
    searchParams.set('usageTab', value);
    setSearchParams(searchParams);
  };

  return (
    <Tabs
      className="custom-tabs"
      defaultActiveKey={tab}
      items={[
        {
          key: USAGE_TABS.consumptions.key,
          label: USAGE_TABS.consumptions.label,
          children: <Consumptions />,
        },
        {
          key: USAGE_TABS.limits.key,
          label: USAGE_TABS.limits.label,
          children: <Limits />,
        },
      ]}
      onChange={handleOnChange}
      sticky
    />
  );
}

const useInitLayoutConfigurations = () => {
  const dispatch = useDispatch();

  useEffect(() => {
    WIDE_MAIN_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
  }, [dispatch]);
};

export default Body;
