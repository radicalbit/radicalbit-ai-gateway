import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import HtmlAnchor from '@Components/html-anchor';
import { PathsEnum, SEARCH_PARAMS, numberFormatterInt } from '@Src/constants';
import {
  Board,
  NewHeader,
  SectionTitle,
} from '@radicalbit/radicalbit-design-system';
import { useGetMostRequestedRouteWithRange } from '@State/routes/vertical-hooks';
import { useNavigate } from 'react-router-dom';
import CounterSkeleton from './counter-skeleton';
import {
  echarts,
  ReactEChartsCore,
  GRANULARITY_LABEL,
  sparklineOption,
  formatIncrement,
} from './options';

const sparklineWidthAndHeight = {
  width: '100%',
  height: '60px',
};

function MostRequested() {
  const { data, isLoading, isError } = useGetMostRequestedRouteWithRange();
  const name = data?.name;

  if (isLoading) {
    return <CounterSkeleton />;
  }

  if (isError) {
    return <IsError />;
  }

  if (!name) {
    return <IsEmpty />;
  }

  return <IsSuccess data={data} />;
}

function IsEmpty() {
  return (
    <Board
      className="flex-1"
      footer={(
        <span className="text-sm text-gray-400" style={sparklineWidthAndHeight}>No data available</span>
      )}
      main={(
        <div className="flex justify-between gap-2 w-full">
          <NewHeader
            padding="none"
            title={(
              <SectionTitle subtitle="No data available" title="Most Requested" />
            )}
          />

          <NewHeader
            padding="none"
            title={(
              <SectionTitle
                align="right"
                subtitle="--"
                title="--"
              />
            )}
          />
        </div>
      )}
    />
  );
}

function IsError() {
  return (
    <Board
      className="flex-1"
      main={<SomethingWentWrong size="xsmall" />}
    />
  );
}

function IsSuccess({ data }) {
  const navigate = useNavigate();
  const { name, incrementPercentage, chart } = data;
  const granularityLabel = GRANULARITY_LABEL[chart?.granularity] || chart?.granularity;
  const formattedTotal = numberFormatterInt(chart?.total ?? 0);
  const formattedIncrement = formatIncrement(incrementPercentage);

  const handleOnClickRouteName = () => {
    const params = new URLSearchParams(window.location.search);
    params.set(SEARCH_PARAMS.routes, name);
    navigate(`/${PathsEnum.ROUTES}/${name}?${params.toString()}`);
  };

  return (
    <Board
      className="flex-1"
      footer={chart && (
        <ReactEChartsCore
          echarts={echarts}
          lazyUpdate
          notMerge={false}
          option={sparklineOption(chart, numberFormatterInt)}
          style={sparklineWidthAndHeight}
        />
      )}
      main={(
        <div className="flex justify-between gap-2 w-full">
          <NewHeader
            padding="none"
            title={(
              <SectionTitle
                subtitle={<HtmlAnchor onClick={handleOnClickRouteName}>{name}</HtmlAnchor>}
                title="Most Requested"
              />
            )}
          />

          <NewHeader
            padding="none"
            title={(
              <SectionTitle
                align="right"
                subtitle={`${formattedIncrement} prev ${granularityLabel}`}
                title={formattedTotal}
              />
            )}
          />
        </div>
      )}
    />
  );
}

export default MostRequested;
