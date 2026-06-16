import { ConfigStatusEnum } from '@Src/constants';
import { useFormbitContext } from '@radicalbit/formbit';
import AceEditor from 'react-ace';

import 'ace-builds/src-noconflict/mode-yaml';
import 'ace-builds/src-noconflict/theme-tomorrow';
import 'ace-builds/src-noconflict/theme-tomorrow_night';
import 'ace-builds/src-noconflict/ext-language_tools';

const EDITOR_OPTIONS = {
  showLineNumbers: true,
  tabSize: 2,
  useWorker: false,
};

function Editor({ config }) {
  if (config.configStatus === ConfigStatusEnum.DRAFT) {
    return <EditorDraft config={config} />;
  }

  return <EditorReadOnly config={config} />;
}

function EditorDraft({ config }) {
  const { form, write } = useFormbitContext();
  const configFile = form?.configs?.[config.uuid] ?? '';

  const isDark = document.body.classList.contains('dark');
  const theme = isDark ? 'tomorrow_night' : 'tomorrow';

  const handleOnChange = (value) => {
    write(`configs.${config.uuid}`, value);
  };

  return (
    <AceEditor
      fontSize={13}
      height="100%"
      mode="yaml"
      name={`project-config-yaml-editor-${config.uuid}`}
      onChange={handleOnChange}
      setOptions={EDITOR_OPTIONS}
      showPrintMargin={false}
      theme={theme}
      value={configFile}
      width="100%"
    />
  );
}

function EditorReadOnly({ config }) {
  const configFile = config.configFile ?? '';

  const isDark = document.body.classList.contains('dark');
  const theme = isDark ? 'tomorrow_night' : 'tomorrow';

  return (
    <AceEditor
      fontSize={13}
      height="100%"
      mode="yaml"
      name={`project-config-yaml-editor-${config.uuid}`}
      readOnly
      setOptions={EDITOR_OPTIONS}
      showPrintMargin={false}
      theme={theme}
      value={configFile}
      width="100%"
    />
  );
}

export default Editor;
