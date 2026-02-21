/* ------------------------------------------------------------------
   TSQueryEditorCode.jsx – React editor component for TS-Workspace
   ------------------------------------------------------------------ */
/* eslint-disable react/require-default-props */

import React from 'react';
import PropTypes from 'prop-types';
import Tooltip from 'antd/lib/tooltip';
import { react2angular } from 'react2angular';

import AceEditor from 'react-ace';
import ace from 'brace';
import EditProjectsDialog from './EditProjectsDialog';
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
import { DataSource } from './proptypes';

import './TSQueryEditor.css';

const orgSlug = window.location.pathname.split('/')[1] || 'api';
const langTools = ace.acequire('ace/ext/language_tools');
const snippetsModule = ace.acequire('ace/snippets');

/* ------------------------------------------------------------------ ensure Ace has empty snippet files */
['python', 'sql', 'json', 'yaml'].forEach((mode) => {
  ace.define(`ace/snippets/${mode}`, ['require', 'exports', 'module'], (_r, e) => {
    // eslint-disable-next-line no-param-reassign
    e.snippetText = '';
    e.scope = mode;
  });
});
/* ------------------------------------------------------------------ */

class TSQueryEditorCode extends React.Component {
  /* ───────────────── propTypes / defaultProps ───────────────── */
  static propTypes = {
    queryId: PropTypes.number.isRequired,
    queryText: PropTypes.string.isRequired,
    schema: PropTypes.arrayOf(
      PropTypes.shape({
        name: PropTypes.string,
        columns: PropTypes.arrayOf(PropTypes.shape({ name: PropTypes.string })),
      }),
    ),
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
    updateQuery: PropTypes.func,
    updateSelectedQuery: PropTypes.func,
    listenForResize: PropTypes.func,
    listenForEditorCommand: PropTypes.func,
    projectIds: PropTypes.arrayOf(PropTypes.number),
  };

  static defaultProps = {
    dataSource: {},
    dataSources: [],
    projectIds: [],
    schema: [],
    listenForResize: () => {},
    listenForEditorCommand: () => {},
    updateQuery: () => {},
    updateSelectedQuery: () => {},
  };

  /* ───────────────── constructor ───────────────── */
  constructor(props) {
    super(props);
    this.editorRef = React.createRef();
    this.state = {
      keywords: { table: [], column: [], tableColumn: [] },
      autocompleteQuery: localOptions.get('liveAutocomplete', true),
      liveAutocompleteDisabled: false,
      queryText: props.queryText,
      selectedProjects: props.projectIds || [],
      queryId: props.queryId,
    };

    /* ---------- schema completer ---------- */
    const schemaCompleter = {
      identifierRegexps: [/[\w.\u00A2-\uFFFF-]/],
      getCompletions: (state, session, pos, prefix, cb) => {
        const { table, column, tableColumn } = this.state.keywords;
        if (!prefix || table.length === 0) { cb(null, []); return; }
        if (prefix.endsWith('.')) {
          const t = prefix.slice(0, -1);
          cb(null, table.concat(tableColumn[t] || []));
          return;
        }
        cb(null, table.concat(column));
      },
    };
    langTools.setCompleters([
      langTools.snippetCompleter,
      langTools.keyWordCompleter,
      langTools.textCompleter,
      schemaCompleter,
    ]);

    this.handleExecute = this.handleExecute.bind(this);
    this.openEditProjectsDialog = this.openEditProjectsDialog.bind(this);
    this.saveProjects = this.saveProjects.bind(this);
    this.resizeAce = this.resizeAce.bind(this);
  }

  /* ───────────── lifecycle ───────────── */
  componentDidMount() {
    const { queryId } = this.state;
    if (queryId) {
      fetch(`/${orgSlug}/api/queries/${queryId}`)
        .then((r) => { if (!r.ok) throw new Error(r.statusText); return r.json(); })
        .then((query) => {
          let saved = [];
          if (query.project_id != null) {
            saved = Array.isArray(query.project_id) ? query.project_id : [query.project_id];
          } else if (query.project_ids && query.project_ids.length) {
            saved = query.project_ids;
          } else if (query.projects && query.projects.length) {
            saved = query.projects.map(p => p.id);
          }
          this.setState({ selectedProjects: saved });
        })
        .catch(() => { /* silent */ });
    }

    window.addEventListener('resize', this.resizeAce);
  }

  componentWillUnmount() {
    window.removeEventListener('resize', this.resizeAce);
  }

  static getDerivedStateFromProps(nextProps, prevState) {
    if (!nextProps.schema || nextProps.schema === prevState.schema) return null;
    const tokenCount = nextProps.schema.reduce((s, t) => s + t.columns.length, 0);
    return {
      keywords: keywordBuilder.buildKeywordsFromSchema(nextProps.schema),
      liveAutocompleteDisabled: tokenCount > 5000,
    };
  }

  /* ───────────── Ace helpers ───────────── */
  onAceLoad = (editor) => {
    editor.commands.bindKey('Cmd+L', null);
    editor.commands.bindKey('Ctrl+P', null);
    editor.commands.bindKey({ win: 'Ctrl+Shift+F', mac: 'Cmd+Shift+F' }, this.formatQuery);
    editor.commands.on('afterExec', (e) => {
      if (e.command.name === 'insertstring' && e.args === '.' && editor.completer) {
        editor.completer.showPopup(editor);
      }
    });

    QuerySnippet.query((snips) => {
      const mgr = snippetsModule.snippetManager;
      const meta = { snippetText: '' };
      meta.snippets = mgr.parseSnippetFile(meta.snippetText);
      snips.forEach(s => meta.snippets.push(s.getSnippet()));
      mgr.register(meta.snippets, meta.scope);
    });

    this.props.listenForResize(() => editor.resize());
    this.props.listenForEditorCommand((_, cmd, ...args) => {
      if (cmd === 'focus') editor.focus();
      if (cmd === 'paste') {
        const [text] = args;
        editor.session.doc.replace(editor.selection.getRange(), text);
        const rng = editor.selection.getRange();
        this.props.updateQuery(editor.getValue());
        editor.selection.setRange(rng);
      }
    });

    setTimeout(this.resizeAce, 0);
  };

  updateSelected = () => {
    const ed = this.editorRef.current.editor;
    const raw = ed.getSession().getTextRange(ed.getSelection().getRange());
    this.props.updateSelectedQuery(raw.length > 1 ? raw : null);
  };

  updateQuery = (q) => {
    this.props.updateQuery(q);
    this.setState({ queryText: q });
  };

  formatQuery = () => {
    Query.format(this.props.dataSource.syntax || 'sql', this.state.queryText)
      .then(this.updateQuery)
      .catch(notification.error);
  };

  toggleAutocomplete = (state) => {
    this.setState({ autocompleteQuery: state });
    localOptions.set('liveAutocomplete', state);
  };

  /* ───────────── miscellaneous helpers (alphabetical) ───────────── */
  openEditProjectsDialog() {
    EditProjectsDialog.showModal({
      queryId: this.state.queryId,
      projects: this.state.selectedProjects,
      getAvailableProjects: () => fetch(`/${orgSlug}/api/available_projects`)
        .then(r => r.json())
        .then(d => [
          ...d.private_projects.map(p => ({ label: p.name, value: p.id })),
          ...d.public_projects.map(p => ({ label: p.name, value: p.id })),
        ])
        .catch(() => []),
    }).result.then((projects) => {
      this.setState({ selectedProjects: projects });
      this.saveProjects(projects);
    });
  }

  saveProjects(projects) {
    fetch(`/${orgSlug}/api/available_projects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query_id: this.state.queryId, project_ids: projects }),
    })
      .then(() => notification.success('Projects updated'))
      .catch(() => notification.error('Update failed'));
  }

  resizeAce() {
    if (this.editorRef.current) this.editorRef.current.editor.resize(true);
  }

  /** Option B – write SQL into Angular scope, then execute */
  handleExecute() {
    const sqlNow = this.editorRef.current
      ? this.editorRef.current.editor.getValue()
      : this.state.queryText;

    try {
      const host = document.querySelector('.query-page-wrapper');
      const ng = window.angular;
      if (ng && host) {
        const scope = ng.element(host).scope();
        if (scope && typeof scope.executeQuery === 'function') {
          scope.$applyAsync(() => {
            scope.query.query = sqlNow;
            scope.isDirty = true;
            scope.executeQuery();
          });
          return;
        }
      }
    } catch (_) { /* ignore */ }

    this.props.updateQuery(sqlNow);
    setTimeout(() => this.props.executeQuery(), 400);
  }

  /* ───────────── render ───────────── */
  render() {
    const {
      canExecuteQuery, queryExecuting, addNewParameter,
      saveQuery, isDirty, canEdit, dataSources, dataSource,
    } = this.props;
    const modKey = KeyboardShortcuts.modKey;

    return (
      <section style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        <div
          className="container p-15 m-b-10"
          style={{ flex: '1 1 auto', minHeight: 0, display: 'flex', flexDirection: 'column' }}
        >
          <div className="editor__container">
            <AceEditor
              ref={this.editorRef}
              theme="textmate"
              mode={dataSource.syntax || 'sql'}
              value={this.state.queryText}
              editorProps={{ $blockScrolling: Infinity }}
              width="100%"
              height="100%"
              setOptions={{
                behavioursEnabled: true,
                enableSnippets: true,
                enableBasicAutocompletion: true,
                enableLiveAutocompletion:
                  !this.state.liveAutocompleteDisabled && this.state.autocompleteQuery,
                autoScrollEditorIntoView: true,
              }}
              showPrintMargin={false}
              wrapEnabled={false}
              onLoad={this.onAceLoad}
              onChange={this.updateQuery}
              onSelectionChange={this.updateSelected}
            />
          </div>

          <div
            className="editor__control"
            style={{ flex: '0 0 auto', background: '#fff', borderTop: '1px solid #e5e5e5', paddingTop: 6 }}
          >
            <div className="form-inline d-flex align-items-center">
              {canEdit && (
                <Tooltip placement="top" title={`${modKey}+S`}>
                  <button
                    type="button"
                    className="btn btn-default m-l-5"
                    onClick={saveQuery}
                    disabled={!isDirty}
                    data-test="SaveButton"
                  >
                    <span className="fa fa-floppy-o" />
                    <span className="hidden-xs m-l-5">Save</span>
                    {isDirty ? '*' : null}
                  </button>
                </Tooltip>
              )}

              <button
                type="button"
                className="btn btn-default m-l-5"
                onClick={this.openEditProjectsDialog}
              >
                <i className="zmdi zmdi-plus m-r-5" />
                Add&nbsp;Project&nbsp;LHCode
              </button>

              <Tooltip placement="top" title="Execute Query">
                <button
                  type="button"
                  className={`btn btn-primary m-l-5${queryExecuting || !canExecuteQuery ? ' disabled' : ''}`}
                  disabled={queryExecuting || !canExecuteQuery}
                  onClick={this.handleExecute}
                  data-test="ExecuteButton"
                >
                  <span className="zmdi zmdi-play" />
                  <span className="hidden-xs m-l-5">Execute</span>
                </button>
              </Tooltip>

              <Tooltip placement="top" title={<span>Add New Parameter (<i>{modKey}+P</i>)</span>}>
                <button
                  type="button"
                  className="btn btn-default m-l-5"
                  onClick={addNewParameter}
                >
                  {'{{ }}'}
                </button>
              </Tooltip>

              <Tooltip placement="top" title={<span>Format Query (<i>{modKey}+Shift+F</i>)</span>}>
                <button
                  type="button"
                  className="btn btn-default m-l-5"
                  onClick={this.formatQuery}
                >
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
                onChange={e => this.props.updateDataSource(Number(e.target.value))}
                disabled={!this.props.isQueryOwner}
                value={dataSource.id || ''}
              >
                {dataSources.map(ds => (
                  <option key={ds.id} value={ds.id}>{ds.name}</option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div style={{ display: 'none' }}>schema size: {this.props.schema.length}</div>
      </section>
    );
  }
}

/* ------------------------------------------------------------------
   Angular registration
   ------------------------------------------------------------------ */
export default function init(ngModule) {
  ngModule.component(
    'tsQueryEditorCode',
    react2angular(TSQueryEditorCode, [
      'queryId', 'queryText', 'schema',
      'addNewParameter', 'dataSources', 'dataSource',
      'canEdit', 'isDirty', 'isQueryOwner',
      'updateDataSource', 'canExecuteQuery', 'executeQuery',
      'queryExecuting', 'saveQuery', 'updateQuery',
      'updateSelectedQuery', 'listenForResize',
      'listenForEditorCommand', 'projectIds',
    ]),
  );
}
init.init = true;
