import { WIDE_MAIN_LAYOUT_CONFIGURATION } from '@Container/layout/layout-provider/layout-provider-configuration';
import Logo from '@Img/logo.png';
import { DEFAULT_POLLING_INTERVAL } from '@Src/constants';
import { useGetAllCostsWithRange } from '@Src/store/state/costs/vertical-hooks';
import {
  Board,
  Button,
  Collapse,
  Skeleton,
  Tabs,
  Void,
} from '@radicalbit/radicalbit-design-system';
import { useEffect, useState } from 'react';
import { useDispatch } from 'react-redux';
import { useSearchParams } from 'react-router-dom';
import './_styles.group-by-tabs.less';
import costFormatter from '@Helpers/cost-formatter';
import CostsGraph from './costs-graph';
import InvocationsGraph from './invocations-graph';
import { Children, Label } from './route-collapse';
import TokensGraph from './tokens-graph';

export const COSTS_GROUP_BY = {
  credentials: {
    key: 'keys',
    label: 'Credentials',
  },
  groups: {
    key: 'groups',
    label: 'Groups',
  },
  models: {
    key: 'models',
    label: 'Models',
  },
};

function CostsList() {
  const { data, isLoading, isError, isSuccess, refetch } = useGetAllCostsWithRange({ withSavedTokens: true });
  const routes = data?.routes || [];
  const count = routes.length;

  usePollingGetAllCosts();
  useInitLayoutConfigurations();

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4 py-4">
        <Skeleton.Input active block />

        <Skeleton.Input active block />

        <Skeleton.Input active block />
      </div>
    );
  }

  if (isError) {
    return <IsError refetch={refetch} />;
  }

  if (!isSuccess) {
    return false;
  }

  return (
    <div className="flex flex-col gap-4 py-4">
      <GroupByTabs />

      {routes.map((route, index) => {
        const { routeName } = route;
        const key = `${routeName}-${index}`;

        return <IsSuccess key={key} count={count} route={route} />;
      })}
    </div>
  );
}

function GroupByTabs() {
  const { data } = useGetAllCostsWithRange({ withSavedTokens: true });
  const total = costFormatter({ cent: data.total });

  const [searchParams, setSearchParams] = useSearchParams();
  const groupBy = searchParams.get('groupBy');

  const handleOnChange = (value) => {
    searchParams.set('groupBy', value);
    setSearchParams(searchParams);
  };

  return (
    <Tabs
      className="custom-tabs"
      defaultActiveKey={groupBy}
      items={[
        {
          key: COSTS_GROUP_BY.groups.key,
          label: COSTS_GROUP_BY.groups.label,
        },
        {
          key: COSTS_GROUP_BY.credentials.key,
          label: COSTS_GROUP_BY.credentials.label,
        },
        {
          key: COSTS_GROUP_BY.models.key,
          label: COSTS_GROUP_BY.models.label,
        },
        {
          key: 'total-cost',
          label: <h1>{total}</h1>,
        },
      ]}
      onChange={handleOnChange}
      sticky
    />
  );
}

// BOOLEANS COMPONENTS

function IsSuccess({ route, count }) {
  const routeName = route?.routeName;

  return (
    <Collapse
      key={`${routeName}-${count}`} // needed to re-render the collapse
      items={[
        {
          key: '1',
          label: <Label route={route} />,
          children: (
            <div className="flex flex-col gap-4">
              <Children route={route} />

              <CostsGraph routeName={routeName} />

              <div className="flex flex-row gap-4 [&>*]:flex-1">
                <TokensGraph routeName={routeName} />

                <InvocationsGraph routeName={routeName} />
              </div>
            </div>),
        },
      ]}
    />
  );
}

function IsError({ refetch }) {
  return (
    <Board
      height="100%"
      main={(
        <Void
          actions={<Button onClick={refetch}>Retry</Button>}
          description={(
            <>
              This might be temporary
              <br />
              please retry later
            </>
          )}
          image={<img alt="Logo" src={Logo} />}
          title="Unable to load costs"
        />
      )}
    />
  );
}

// VERTICAL HOOKS

const usePollingGetAllCosts = () => {
  const [pollingInterval, setPollingInterval] = useState(DEFAULT_POLLING_INTERVAL);

  const { isError } = useGetAllCostsWithRange({ withSavedTokens: true }, { pollingInterval });

  useEffect(() => {
    if (isError) {
      setPollingInterval(0);
    } else {
      setPollingInterval(DEFAULT_POLLING_INTERVAL);
    }
  }, [isError]);
};

const useInitLayoutConfigurations = () => {
  const dispatch = useDispatch();

  useEffect(() => {
    WIDE_MAIN_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
  }, [dispatch]);
};

export default CostsList;
