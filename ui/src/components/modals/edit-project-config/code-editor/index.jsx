import { Board } from '@radicalbit/radicalbit-design-system';
import useGetActiveConfig from '../useGetActiveConfig';
import Actions from './actions';
import Editor from './editor';
import Feedbacks from './feedbacks';
import Header from './header';

function CodeEditor() {
  const { activeConfig, configs, projectUuid, selectConfig } = useGetActiveConfig();

  if (!activeConfig) {
    return false;
  }

  return (
    <div className="flex flex-col min-h-0 gap-2 h-full">

      <Feedbacks config={activeConfig} />

      <Header
        activeConfigUuid={activeConfig.uuid}
        configs={configs}
        onSelectConfig={selectConfig}
      />

      <Board
        className="flex-1 min-h-0"
        main={(
          <div className="flex flex-col h-full min-h-0 gap-2">

            <div className="flex-1 min-h-0">
              <Editor config={activeConfig} />
            </div>
          </div>
        )}
        overflow="hidden"
        size="xsmall"
      />

      <div className="flex justify-center gap-2">
        <Actions config={activeConfig} projectUuid={projectUuid} />
      </div>
    </div>
  );
}

export default CodeEditor;
