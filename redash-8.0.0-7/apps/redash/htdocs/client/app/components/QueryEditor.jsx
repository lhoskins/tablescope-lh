import React from 'react';
import PropTypes from 'prop-types';
import Tooltip from 'antd/lib/tooltip';
import { react2angular } from 'react2angular';

import AceEditor from 'react-ace';
import ace from 'brace';
import EditProjectsDialog from './EditProjectsDialog'; // Import the dialog
import notification from '@/services/notification';

import 'brace/ext/language_tools';
import 'brace/mode/json';
import 'brace/mode/python';
import 'brace/mode/sql';
import 'brace/mode/yaml';
import 'brace/theme/textmate';
import 'brace/ext/searchbox';

import { Query } from '@/services/query';
import { QuerySnippet } from '@/services/query-snippet';
import { KeyboardShortcuts } from '@/services/keyboard-shortcuts';

import localOptions from '@/lib/localOptions';
import AutocompleteToggle from '@/components/AutocompleteToggle';
import keywordBuilder from './keywordBuilder';
import { DataSource, Schema } from './proptypes';

import './QueryEditor.css';

// Dynamically extract the organization slug from the URL.
const orgSlug = window.location.pathname.split('/')[1] || 'api';

const langTools = ace.acequire('ace/ext/language_tools');
const snippetsModule = ace.acequire('ace/snippets');

// Dummy snippet definitions so Ace doesn't try to load external snippet files.
function defineDummySnippets(mode) {
  ace.define(`ace/snippets/${mode}`, ['require', 'exports', 'module'], (require, exports) => {
    exports.snippetText = '';
    exports.scope = mode;
  });
}
defineDummySnippets('python');
defineDummySnippets('sql');
defineDummySnippets('json');
defineDummySnippets('yaml');

class QueryEditor extends React.Component {
  static propTypes = {
    // queryId is required and passed from query.html (e.g. query-id="query.id")
    queryId: PropTypes.number.isRequired,
    queryText: PropTypes.string.isRequired,
    schema: Schema,
    addNewParameter: PropTypes.func.isRequired,
    dataSources: PropTypes.arrayOf(DataSource),
    dataSource: DataSource,
    canEdit: PropTypes.bool.isRequired,
    isDirty: PropTypes.bool.isRequired,
    isQueryOwner: PropTypes.bool.isRequired,
    updateDataSource: PropTypes.func.isRequired,
    canExecuteQuery: PropTypes.bool.isRequired,
    executeQuery: PropTypes.func.isRequired,
    queryExecuting: PropTypes.bool.isRequired,
    saveQuery: PropTypes.func.isRequired,
    updateQuery: PropTypes.func.isRequired,
    updateSelectedQuery: PropTypes.func.isRequired,
    listenForResize: PropTypes.func.isRequired,
    listenForEditorCommand: PropTypes.func.isRequired,
    projectIds: PropTypes.arrayOf(PropTypes.number),
  };

  static defaultProps = {
    schema: null,
    dataSource: {},
    dataSources: [],
    projectIds: [],
  };

  constructor(props) {
    super(props);
    this.refEditor = React.createRef();

    console.debug('[QueryEditor] Constructor: queryId =', props.queryId);
    console.debug('[QueryEditor] Constructor: projectIds =', props.projectIds);

    this.state = {
      schema: null,
      keywords: { table: [], column: [], tableColumn: [] },
      autocompleteQuery: localOptions.get('liveAutocomplete', true),
      liveAutocompleteDisabled: false,
      queryText: props.queryText,
      selectedProjects: props.projectIds || [],
      queryId: props.queryId, // store the passed queryId in state
    };

    const schemaCompleter = {
      identifierRegexps: [/[a-zA-Z_0-9.\-\u00A2-\uFFFF]/],
      getCompletions: (state, session, pos, prefix, callback) => {
        const { table, column, tableColumn } = this.state.keywords;
        if (prefix.length === 0 || table.length === 0) {
          callback(null, []);
          return;
        }
        if (prefix[prefix.length - 1] === '.') {
          const tableName = prefix.substring(0, prefix.length - 1);
          callback(null, table.concat(tableColumn[tableName] || []));
          return;
        }
        callback(null, table.concat(column));
      },
    };

    langTools.setCompleters([
      langTools.snippetCompleter,
      langTools.keyWordCompleter,
      langTools.textCompleter,
      schemaCompleter,
    ]);
  }

  componentDidMount() {
    const { queryId } = this.state;

    if (!queryId) {
      console.error('[QueryEditor] queryId is undefined. Unable to fetch query details.');
      return;
    }
    // Fetch query details using the passed queryId.
    window.fetch(`/${orgSlug}/api/queries/${queryId}`)
      .then((response) => {
        if (!response.ok) {
          throw new Error(response.statusText);
        }
        return response.json();
      })
      .then((query) => {
        console.debug('[QueryEditor] Loaded query details:', query);
        let savedProjects = [];
        if (query.project_id !== undefined && query.project_id !== null) {
          savedProjects = Array.isArray(query.project_id) ? query.project_id : [query.project_id];
          console.debug('[QueryEditor] Setting selectedProjects from query.project_id:', savedProjects);
        } else if (query.project_ids && query.project_ids.length > 0) {
          savedProjects = query.project_ids;
          console.debug('[QueryEditor] Setting selectedProjects from query.project_ids:', savedProjects);
        } else if (query.projects && query.projects.length > 0) {
          savedProjects = query.projects.map(p => p.id);
          console.debug('[QueryEditor] Setting selectedProjects from query.projects:', savedProjects);
        } else {
          console.debug('[QueryEditor] No saved project IDs found in query details.');
        }
        this.setState({ selectedProjects: savedProjects });
      })
      .catch((error) => {
        console.error('[QueryEditor] Failed to load query details:', error);
      });
  }

  static getDerivedStateFromProps(nextProps, prevState) {
    if (!nextProps.schema) {
      return { keywords: { table: [], column: [], tableColumn: [] }, liveAutocompleteDisabled: false };
    } else if (nextProps.schema !== prevState.schema) {
      const tokensCount = nextProps.schema.reduce((total, table) => total + table.columns.length, 0);
      return {
        schema: nextProps.schema,
        keywords: keywordBuilder.buildKeywordsFromSchema(nextProps.schema),
        liveAutocompleteDisabled: tokensCount > 5000,
      };
    }
    return null;
  }

  onLoad = (editor) => {
    editor.commands.bindKey('Cmd+L', null);
    editor.commands.bindKey('Ctrl+P', null);
    editor.commands.bindKey('Ctrl+L', null);
    editor.commands.bindKey({ win: 'Ctrl+P', mac: null }, null);
    editor.commands.bindKey({ win: null, mac: 'Ctrl+P' }, 'golineup');
    editor.commands.bindKey({ win: 'Ctrl+Shift+F', mac: 'Cmd+Shift+F' }, this.formatQuery);

    editor.commands.on('afterExec', (e) => {
      if (e.command.name === 'insertstring' && e.args === '.' && editor.completer) {
        editor.completer.showPopup(editor);
      }
    });

    QuerySnippet.query((snippets) => {
      const snippetManager = snippetsModule.snippetManager;
      const m = { snippetText: '' };
      m.snippets = snippetManager.parseSnippetFile(m.snippetText);
      snippets.forEach((snippet) => {
        m.snippets.push(snippet.getSnippet());
      });
      snippetManager.register(m.snippets || [], m.scope);
    });

    editor.focus();
    console.debug('[QueryEditor] onLoad called. QueryId =', this.state.queryId);
    this.props.listenForResize(() => editor.resize());
    this.props.listenForEditorCommand((e, command, ...args) => {
      switch (command) {
        case 'focus':
          editor.focus();
          break;
        case 'paste': {
          const [text] = args;
          editor.session.doc.replace(editor.selection.getRange(), text);
          const range = editor.selection.getRange();
          this.props.updateQuery(editor.session.getValue());
          editor.selection.setRange(range);
          break;
        }
        default:
          break;
      }
    });
  };

  updateSelectedQuery = (selection) => {
    const { editor } = this.refEditor.current;
    const doc = editor.getSession().doc;
    const rawSelectedQueryText = doc.getTextRange(selection.getRange());
    const selectedQueryText = rawSelectedQueryText.length > 1 ? rawSelectedQueryText : null;
    this.props.updateSelectedQuery(selectedQueryText);
  };

  updateQuery = (queryText) => {
    this.props.updateQuery(queryText);
    this.setState({ queryText });
  };

  formatQuery = () => {
    Query.format(this.props.dataSource.syntax || 'sql', this.props.queryText)
      .then(this.updateQuery)
      .catch((error) => {
        console.debug('[QueryEditor] formatQuery error:', error);
        notification.error(error);
      });
  };

  toggleAutocomplete = (state) => {
    this.setState({ autocompleteQuery: state });
    localOptions.set('liveAutocomplete', state);
  };

  componentDidUpdate = () => {
    const { editor } = this.refEditor.current;
    editor.resize();
  };

  openEditProjectsDialog = () => {
    console.debug('[QueryEditor] openEditProjectsDialog called.');
    console.debug('[QueryEditor] Current selectedProjects state:', this.state.selectedProjects);
    // Pass the queryId along with the current projects to EditProjectsDialog.
    EditProjectsDialog.showModal({
      queryId: this.state.queryId,
      projects: this.state.selectedProjects || [],
      getAvailableProjects: () => {
        console.debug('[QueryEditor] getAvailableProjects called. Fetching combined projects.');
        return window.fetch(`/${orgSlug}/api/available_projects`)
          .then((response) => {
            console.debug('[QueryEditor] Available projects fetch response:', response);
            if (!response.ok) {
              throw new Error(response.statusText);
            }
            return response.json();
          })
          .then((data) => {
            console.debug('[QueryEditor] Available projects fetch data:', data);
            if (data && data.private_projects && data.public_projects) {
              const privateProjects = data.private_projects.map(p => ({ label: p.name, value: p.id }));
              const publicProjects = data.public_projects.map(p => ({ label: p.name, value: p.id }));
              const allProjects = [...privateProjects, ...publicProjects];
              return Array.from(new Map(allProjects.map(p => [p.value, p])).values());
            }
            return [];
          })
          .catch(() => {
            console.error('[QueryEditor] Available projects fetch error');
            return [];
          });
      },
    }).result.then((selectedProjects) => {
      console.debug('[QueryEditor] Received selectedProjects from EditProjectsDialog:', selectedProjects);
      this.setState({ selectedProjects });
      this.saveProjects(selectedProjects);
    });
  };

  saveProjects = (selectedProjects) => {
    const { queryId } = this.state;
    console.debug('[QueryEditor] Saving projects. Using QueryId:', queryId, 'SelectedProjects:', selectedProjects);
    window.fetch(`/${orgSlug}/api/available_projects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query_id: queryId, project_ids: selectedProjects }),
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(response.statusText);
        }
        return response.json();
      })
      .then(() => {
        notification.success('Projects updated successfully!');
      })
      .catch(() => {
        notification.error('Failed to update projects.');
      });
  };

  render() {
    const modKey = KeyboardShortcuts.modKey;
    const { queryId } = this.props;
    return (
      <section style={{ height: '100%' }} data-test="QueryEditor">
        <div className="container p-15 m-b-10" style={{ height: '100%' }}>
          <div
            data-executing={this.props.queryExecuting}
            style={{ height: 'calc(100% - 40px)', marginBottom: '0px' }}
            className="editor__container"
          >
            <AceEditor
              ref={this.refEditor}
              theme="textmate"
              mode={this.props.dataSource.syntax || 'sql'}
              value={this.state.queryText}
              editorProps={{ $blockScrolling: Infinity }}
              width="100%"
              height="100%"
              setOptions={{
                behavioursEnabled: true,
                enableSnippets: true,
                enableBasicAutocompletion: true,
                enableLiveAutocompletion: !this.state.liveAutocompleteDisabled && this.state.autocompleteQuery,
                autoScrollEditorIntoView: true,
              }}
              showPrintMargin={false}
              wrapEnabled={false}
              onLoad={this.onLoad}
              onPaste={this.onPaste}
              onChange={this.updateQuery}
              onSelectionChange={this.updateSelectedQuery}
            />
          </div>
          <div className="editor__control">
            <div className="form-inline d-flex align-items-center">
              <Tooltip placement="top" title="Execute Query">
                <button
                  type="button"
                  className={`btn btn-primary m-l-5${this.props.queryExecuting || !this.props.canExecuteQuery ? ' disabled' : ''}`}
                  disabled={this.props.queryExecuting || !this.props.canExecuteQuery}
                  onClick={this.props.executeQuery}
                  data-test="ExecuteButton"
                >
                  <span className="zmdi zmdi-play" />
                  <span className="hidden-xs m-l-5">Execute</span>
                </button>
              </Tooltip>
              <Tooltip placement="top" title={<span>Add New Parameter (<i>{modKey} + P</i>)</span>}>
                <button type="button" className="btn btn-default m-l-5" onClick={this.props.addNewParameter}>
                  &#123;&#123;&nbsp;&#125;&#125;
                </button>
              </Tooltip>
              <Tooltip placement="top" title={<span>Format Query (<i>{modKey} + Shift + F</i>)</span>}>
                <button type="button" className="btn btn-default m-l-5" onClick={this.formatQuery}>
                  <span className="zmdi zmdi-format-indent-increase" />
                </button>
              </Tooltip>
              <AutocompleteToggle
                state={this.state.autocompleteQuery}
                onToggle={this.toggleAutocomplete}
                disabled={this.state.liveAutocompleteDisabled}
              />
              <select
                className="form-control datasource-small flex-fill w-100 m-l-5"
                onChange={this.props.updateDataSource}
                disabled={!this.props.isQueryOwner}
              >
                {this.props.dataSources.map(ds => (
                  <option label={ds.name} value={ds.id} key={`ds-option-${ds.id}`}>
                    {ds.name}
                  </option>
                ))}
              </select>
              {this.props.canEdit && (
                <Tooltip placement="top" title={`${modKey} + S`}>
                  <button
                    type="button"
                    className="btn btn-default m-l-5"
                    onClick={this.props.saveQuery}
                    data-test="SaveButton"
                    title="Save"
                  >
                    <span className="fa fa-floppy-o" />
                    <span className="hidden-xs m-l-5">Save</span>
                    {this.props.isDirty ? '*' : null}
                  </button>
                </Tooltip>
              )}
              <div className="d-flex align-items-center ml-auto">
                <button
                  type="button"
                  className="btn btn-default m-l-5"
                  onClick={this.openEditProjectsDialog}
                >
                  <i className="zmdi zmdi-plus m-r-5" />
                  Add Project
                </button>
              </div>
            </div>
          </div>
        </div>
        <div style={{ display: 'none' }}>
          Query ID: {queryId} - Schema: {this.props.schema ? JSON.stringify(this.props.schema) : null}
        </div>
      </section>
    );
  }
}

export default function init(ngModule) {
  ngModule.component('queryEditor', react2angular(QueryEditor, null, ['$http']));
}

init.init = true;
