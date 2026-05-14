import { WIDE_MAIN_LAYOUT_CONFIGURATION } from '@Container/layout/layout-provider/layout-provider-configuration';
import { useGetAppConfigurationsQuery } from '@Src/store/state/configurations/api';
import { useEffect } from 'react';
import { useDispatch } from 'react-redux';
import CodeBlock from '@Components/code-block';
import CodeBlockRawText from '@Components/code-block/raw-text';
import { Board, Button, Skeleton, Void } from '@radicalbit/radicalbit-design-system';
import Logo from '@Img/logo.png';

function ConfigDetail() {
  const { data, isLoading, isError, isFetching, refetch } = useGetAppConfigurationsQuery();
  const configFile = data?.configFile;

  useInitLayoutConfigurations();

  if (isLoading) {
    return (
      <Board
        borderType="none"
        main={(
          <Skeleton.Input
            active
            block
            className="flex-1"
            style={{
              height: '80vh',
              borderRadius: 8,
            }}
          />
        )}
      />
    );
  }

  if (isError) {
    return <IsError isFetching={isFetching} refetch={refetch} />;
  }

  return (
    <Board
      borderType="none"
      main={(
        <CodeBlock code={configFile} defaultFontSize={1} hasCopyToClipboard isFontResizable>
          <CodeBlockRawText text={configFile} />
        </CodeBlock>
      )}
    />
  );
}

function IsError({ refetch, isFetching }) {
  return (
    <Board
      height="100%"
      main={(
        <Void
          actions={<Button loading={isFetching} onClick={refetch}>Retry</Button>}
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

const useInitLayoutConfigurations = () => {
  const dispatch = useDispatch();

  useEffect(() => {
    WIDE_MAIN_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
  }, [dispatch]);
};

export default ConfigDetail;
