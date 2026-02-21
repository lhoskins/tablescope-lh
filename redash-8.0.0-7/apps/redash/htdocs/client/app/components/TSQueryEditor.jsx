import isEqual from 'lodash/isEqual';
/* eslint-disable react/require-default-props, camelcase, class-methods-use-this, react/sort-comp */

import React from 'react';
import PropTypes from 'prop-types';
import Tooltip from 'antd/lib/tooltip';
import { react2angular } from 'react2angular';
import {
  Box,
  Typography,
  TextField as MuiTextField,
  IconButton as MuiIconButton,
  FormControlLabel as MuiFormControlLabel,
  Checkbox as MuiCheckbox,
} from '@material-ui/core';
import CloseIcon from '@material-ui/icons/Close';
import ExpandMoreIcon from '@material-ui/icons/ExpandMore';
import ChevronRightIcon from '@material-ui/icons/ChevronRight';

import AceEditor from 'react-ace';
import ace from 'brace';
import notification from '@/services/notification';

import 'brace/ext/language_tools';
import 'brace/mode/json';
import 'brace/mode/python';
import 'brace/mode/sql';
import 'brace/mode/yaml';
import 'brace/theme/textmate';
import 'brace/ext/searchbox';

import currentUser from '@/services/user';
import { Query } from '@/services/query';
import { QuerySnippet } from '@/services/query-snippet';
import { KeyboardShortcuts } from '@/services/keyboard-shortcuts';

import { QueryBuilder, formatQuery, parseSQL } from 'react-querybuilder';
import 'react-querybuilder/dist/query-builder.css';
import JoinBuilder from './JoinBuilder';

import localOptions from '@/lib/localOptions';
import AutocompleteToggle from '@/components/AutocompleteToggle';
import keywordBuilder from './keywordBuilder';
import { DataSource } from './proptypes';

import { DataGrid } from '@material-ui/data-grid';

import './TSQueryEditor.css';
import tsqueryTemplate from '@/pages/queries/TSquery.html';
import QueryViewCtrl from '@/pages/queries/TSview';
import EditProjectsDialog from './EditProjectsDialog';


/* ------------------------------------------------------------------ */
/* ★ NEW – define orgSlug so URLs work correctly                     */
/* ------------------------------------------------------------------ */
const orgSlug = window.location.pathname.split('/')[1] || 'api';

/**
 * Helper to poll for a Redash query job result.
 * When a query is forced to re-execute with max_age=0, Redash returns a job object.
 * We then need to poll the job API until the job is complete (status 3) or fails (status 4).
 * @param {string} jobId The ID of the job to poll.
 */
async function pollJob(jobId) {
  const jobUrl = `/${orgSlug}/api/jobs/${jobId}`;
  let jobResult;
  let retries = 20; // Poll for a max of 20 seconds

  while (retries > 0) {
    // eslint-disable-next-line no-await-in-loop
    const jobRes = await fetch(jobUrl, { credentials: 'same-origin' });
    if (!jobRes.ok) {
      throw new Error('Job status check failed');
    }
    // eslint-disable-next-line no-await-in-loop
    jobResult = await jobRes.json();

    if (jobResult.job.status === 3) { // 3 = success
      // eslint-disable-next-line no-await-in-loop
      const resultRes = await fetch(`/${orgSlug}/api/query_results/${jobResult.job.query_result_id}`, { credentials: 'same-origin' });
      if (!resultRes.ok) {
        throw new Error('Failed to fetch query result after job completion');
      }
      return resultRes.json();
    }

    if (jobResult.job.status === 4) { // 4 = error
      throw new Error(`Query execution for preview failed: ${jobResult.job.error || 'Unknown error'}`);
    }

    // Wait for 1 second before polling again
    // eslint-disable-next-line no-await-in-loop
    await new Promise(resolve => setTimeout(resolve, 1000));
    retries -= 1;
  }
  throw new Error('Query execution for preview timed out.');
}


/* ------------------------------------------------------------------ */
/* ★ NEW – MUI controls for React Query Builder grid                 */
/* ------------------------------------------------------------------ */
/* ─── FIELD SELECTOR ───────────────────────────────────────────── */
const FieldSelector = ({ options = [], value, handleOnChange }) => (
  <select
    value={value}
    onChange={e => handleOnChange(e.target.value)}
    style={{
      display: 'block',
      width: '100%',
      padding: '4px 8px',
      fontSize: '0.875rem',
      boxSizing: 'border-box',
      borderRadius: 4,
      border: '1px solid #ccc',
    }}
  >
    <option value="" disabled>
      Select Field
    </option>
    {options.map(o => (
      <option key={o.name || o} value={o.name || o}>
        {o.label || o}
      </option>
    ))}
  </select>
);
FieldSelector.propTypes = {
  options: PropTypes.array,
  value: PropTypes.string,
  handleOnChange: PropTypes.func,
};
FieldSelector.defaultProps = {
  options: [],
  value: '',
  handleOnChange: () => {},
};

/* ─── OPERATOR SELECTOR ────────────────────────────────────────── */
const OperatorSelector = ({ options = [], value, handleOnChange }) => (
  <select
    value={value}
    onChange={e => handleOnChange(e.target.value)}
    style={{
      display: 'block',
      width: '100%',
      padding: '4px 8px',
      fontSize: '0.875rem',
      boxSizing: 'border-box',
      borderRadius: 4,
      border: '1px solid #ccc',
    }}
  >
    <option value="" disabled>
      Select Condition
    </option>
    {options.map(o => (
      <option key={o.value || o} value={o.value || o}>
        {o.label || o}
      </option>
    ))}
  </select>
);
OperatorSelector.propTypes = {
  options: PropTypes.array,
  value: PropTypes.string,
  handleOnChange: PropTypes.func,
};
OperatorSelector.defaultProps = {
  options: [],
  value: '',
  handleOnChange: () => {},
};

/* ─── VALUE EDITOR ─────────────────────────────────────────────── */
const ValueEditor = ({ value, handleOnChange }) => (
  <MuiTextField
    value={value}
    size="small"
    variant="outlined"
    fullWidth
    onChange={e => handleOnChange(e.target.value)}
  />
);
ValueEditor.propTypes = {
  value: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  handleOnChange: PropTypes.func,
};
ValueEditor.defaultProps = {
  value: '',
  handleOnChange: () => {},
};

/* ─── CONJUNCTION SELECTOR (AND / OR) ─────────────────────────── */
const ConjunctionSelector = ({ options = [], value, handleOnChange }) => (
  <select
    value={value}
    onChange={e => handleOnChange(e.target.value)}
    style={{
      display: 'block',
      width: '100%',
      padding: '4px 8px',
      fontSize: '0.875rem',
      boxSizing: 'border-box',
      borderRadius: 4,
      border: '1px solid #ccc',
    }}
  >
    {options.map(o => (
      <option key={o.id || o} value={o.id || o}>
        {o.label || o}
      </option>
    ))}
  </select>
);
ConjunctionSelector.propTypes = {
  options: PropTypes.array,
  value: PropTypes.string,
  handleOnChange: PropTypes.func,
};
ConjunctionSelector.defaultProps = {
  options: [],
  value: '',
  handleOnChange: () => {},
};

/* ─── REMOVE RULE ACTION (X) ──────────────────────────────────── */
const RemoveRuleAction = ({ handleOnClick }) => (
  <MuiIconButton size="small" onClick={handleOnClick}>
    <CloseIcon fontSize="small" />
  </MuiIconButton>
);
RemoveRuleAction.propTypes = {
  handleOnClick: PropTypes.func,
};
RemoveRuleAction.defaultProps = {
  handleOnClick: () => {},
};

/* Combine into rqbControls for QueryBuilder */
const rqbControls = {
  fieldSelector: FieldSelector,
  operatorSelector: OperatorSelector,
  valueEditor: ValueEditor,
  combinatorSelector: ConjunctionSelector,
  removeRuleAction: RemoveRuleAction,
};

/* ------------------------------------------------------------------ */
/* ★ NEW helpers                                                      */
/* ------------------------------------------------------------------ */
/** pull the first table name found after FROM */
const extractTableName = (sql) => {
  if (!sql) return null;
  const m = /from\s+([^\s;\n]+)/i.exec(sql);
  return m ? m[1].trim() : null;
};

/** pull the first JOIN table name (assumes “… JOIN <tablename> ON …”) */
const extractJoinTableName = (sql) => {
  if (!sql) return null;
  const m = /join\s+([^\s;\n]+)\s+on/i.exec(sql);
  return m ? m[1].trim() : null;
};

/** pull the raw JOIN clause (e.g. “INNER JOIN foo ON f.id = b.id”) */
const extractRawJoinClause = (sql) => {
  if (!sql) return '';
  const m = /((?:inner|left|right|full)?\s*join\s+[^\s;]+\s+on\s+[^;\n]+)/i.exec(sql);
  return m ? stripWhere(m[1].trim()) : '';
};

/** helper: remove anything from first WHERE onward */
const stripWhere = s => (s || '').split(/\bWHERE\b/i)[0].trim();


/** pull a comma-separated list of columns from SELECT */
const extractSelectedFields = (sql) => {
  if (!sql) return [];
  const selectMatch = sql.match(/select\s+([\s\S]+?)\s+from/i);
  if (!selectMatch) return [];
  const colsPart = selectMatch[1];
  return colsPart
    .split(',')
    .map(c => c.trim())
    .filter(c => c !== '*' && c.length);
};

/**
 * Rudimentary parser to extract simple WHERE clauses connected by AND.
 * Only handles conditions of form: <field> <op> <value> (no OR, no nesting).
 */
const extractWhereRules = (sql, tableName) => {
  if (!sql) return { combinator: 'and', rules: [] };
  const whereMatch = sql.match(/where\s+([\s\S]+)$/i);
  if (!whereMatch) return { combinator: 'and', rules: [] };
  const condStr = whereMatch[1].trim().replace(/;$/, '');
  // Split on AND
  const parts = condStr.split(/\s+and\s+/i);
  const rules = parts.map((part) => {
    const m = part.match(/([\w.]+)\s*(=|<>|<|>|<=|>=|like)\s*(.+)/i);
    if (m) {
      let [, field, operator, value] = m;
      value = value.trim().replace(/;$/, '');
      // Strip quotes if present
      if (
        (value.startsWith("'") && value.endsWith("'")) ||
        (value.startsWith('"') && value.endsWith('"'))
      ) {
        value = value.slice(1, -1);
      }
      // Prefix field with tableName if no dot present
      if (!field.includes('.')) {
        field = `${tableName}.${field}`;
      }
      return { field, operator: operator.toLowerCase(), value };
    }
    return null;
  });
  return { combinator: 'and', rules: rules.filter(r => r !== null) };
};

/* ------------------------------------------------------------------ */
/* Component                                                          */
/* ------------------------------------------------------------------ */
class TSQueryEditor extends React.Component {
  /* ---------- propTypes / defaultProps ---------- */
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
    isNew: PropTypes.bool,
    projectId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
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
    isNew: false,
    projectId: null,
  };

  constructor(props) {
    super(props);
    this.editorRef = React.createRef();

    /**
     * 1) Parse out initial leftTableName from “FROM <table>”
     * 2) Parse out initial rightTableName from “JOIN <table> ON …”
     * 3) Parse raw joinClause so we can re-inject later
     * 4) Parse SELECTed fields (if not “*”) so we can “pre-select” those columns
     * 5) Parse WHERE so we can build an initial ruleTree
     */
    const incomingSQL = (props.queryText || '').trim(); // Trim the incoming SQL
    let initialRuleTree;

    // Safely parse the incoming SQL
    try {
      if (incomingSQL) {
        initialRuleTree = parseSQL(incomingSQL, { listsAsArrays: true });
      } else {
        // For new or empty queries, use a default empty rule set.
        initialRuleTree = { combinator: 'and', rules: [] };
      }
    } catch (e) {
      // If parsing fails, log the error and fall back to a safe default.
      console.error('Failed to parse initial SQL. Falling back to an empty state.', {
        sql: incomingSQL,
        error: e,
      });
      notification.error('The initial query is invalid and could not be parsed for the visual editor.');
      initialRuleTree = { combinator: 'and', rules: [] };
    }

    const parsedLeft = extractTableName(incomingSQL) || '';
    const parsedRight = extractJoinTableName(incomingSQL) || '';
    const rawJoin = extractRawJoinClause(incomingSQL);
    const rawSelected = extractSelectedFields(incomingSQL);

    this.state = {
      previewVersion: 0,
      previewReady: { left: false, right: false },

      keywords: { table: [], column: [], tableColumn: [] },
      autocompleteQuery: localOptions.get('liveAutocomplete', true),
      liveAutocompleteDisabled: false,

      /** The live SQL text (may be modified by user or by visual builder) */
      queryText: props.queryText,

      /** For new queries, the name of the query */
      name: props.isNew ? 'New Query' : '',

      /** Currently selected data_source_id (derived from table clicks) */
      selectedDataSourceId: (props.dataSource && props.dataSource.id) || null,

      /** Projects (unchanged) */
      selectedProjects: props.projectIds || [],
      queryId: props.queryId,

      /* SQL editor initial height (px) */
      sqlEditorHeight: localOptions.get('tsqeSqlHeight', 360),
      /* visual mode — default now opens the Visual Builder */
      mode: 'visual', // 'sql' | 'visual'
      visualQuery: initialRuleTree, // start with any WHERE‐clauses parsed out

      /* join components */
      joinClause: rawJoin,
      joinType: 'INNER',
      joinOperand: '=',
      selectedLeft: [],
      selectedRight: [],

      /* fetched list w/ real table names */
      queriesList: [],

      /* available fields for RQB once join changes */
      rqbAvailableFields: [],

      /* ★ NEW: track the chosen left table (for FROM) */
      leftTableName: parsedLeft,

      /* ★ NEW: track the chosen right table (for informational) */
      rightTableName: parsedRight,

      /* ★ NEW: whether join controls (secondary & relation) are visible */
      joinClicked: !!parsedRight,

      /* ★ NEW: initial column selections from SELECT clause (unprefixed) */
      initialSelectedColsRaw: rawSelected,

      /* ★ NEW: preview columns and rows (populated from API) */
      leftPreview: { columns: [], rows: [] },
      rightPreview: { columns: [], rows: [] },
      expandedTables: {},
      schemaWidth: 420,
      schemaFilter: '',
      localCanExecute: !props.isNew,
      projectDataSources: [],
      expandedDataSources: {}, // Track which data sources are expanded { dataSourceId: true/false }
      dataSourceSchemas: {}, // Cache schemas { dataSourceId: [tables] }
      tableSearchTerms: {}, // Track search terms for each data source { dataSourceId: 'search term' }
    };

    /** *** Ace completer setup (unchanged) **** */
    const langTools = ace.acequire('ace/ext/language_tools');
    const snippetsModule = ace.acequire('ace/snippets');
    const schemaCompleter = {
      identifierRegexps: [/[\w.\u00A2-\uFFFF-]/],
      getCompletions: (state, session, pos, prefix, cb) => {
        const { table, column, tableColumn } = this.state.keywords;
        if (!prefix || table.length === 0) {
          cb(null, []);
          return;
        }
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
    ['python', 'sql', 'json', 'yaml'].forEach((mode) => {
      ace.define(
        `ace/snippets/${mode}`,
        ['require', 'exports', 'module'],
        (_r, e) => {
          e.snippetText = '';
          e.scope = mode;
        },
      );
    });
  }

  /* ---------------- Horizontal resize for schema browser ---------------- */
  startHResize = (e) => {
    e.preventDefault();
    document.addEventListener('mousemove', this.onHResize);
    document.addEventListener('mouseup', this.stopHResize);
  };

  onHResize = (e) => {
    this.setState({ schemaWidth: Math.max(180, e.clientX) });
  };

  stopHResize = () => {
    document.removeEventListener('mousemove', this.onHResize);
    document.removeEventListener('mouseup', this.stopHResize);
  };

  /* ---------------- helpers ---------------- */
  getCurrentProjectId = () => (
    window.__currentProjectId ||
      window.query?.project_id?.[0] ||
      window.queryResult?.query?.project_id?.[0] ||
      null
  )

  /**
   * ★ FIXED: This function is now a class method.
   * Load project data sources, same as ProjectDetailPage cards.
   */
  fetchProjectDataSources = async (projectId) => {
    if (!projectId) return;
    try {
      const res = await fetch(`/${orgSlug}/api/projects/${projectId}`, { credentials: 'same-origin' });
      if (!res.ok) throw new Error(res.statusText);
      const proj = await res.json();
      const list = (proj.data_sources || []).map(d => d.data_source || d);
      this.setState({ projectDataSources: list });
      console.log('[TSQueryEditor] projectDataSources →', list);
    } catch (e) { console.error('[TSQueryEditor] fetchProjectDataSources error', e); }
  };

  /**
   * Fetch schema (tables) for a specific data source
   * External type data sources will not have schemas
   */
  fetchDataSourceSchema = async (dataSourceId, dataSourceType) => {
    // Skip fetching schema for external data sources (file-based virtual databases)
    if (dataSourceType === 'external') {
      console.log('[TSQueryEditor] Skipping schema fetch for external data source');
      return [];
    }

    try {
      const res = await fetch(`/${orgSlug}/api/data_sources/${dataSourceId}/schema`, { 
        credentials: 'same-origin' 
      });
      if (!res.ok) throw new Error(res.statusText);
      const data = await res.json();
      const tables = data.schema || [];
      console.log(`[TSQueryEditor] Fetched schema for data source ${dataSourceId}:`, tables);
      return tables;
    } catch (e) {
      console.error(`[TSQueryEditor] fetchDataSourceSchema error for ${dataSourceId}:`, e);
      return [];
    }
  };

  /**
   * Toggle data source expansion and fetch schema if needed
   */
  toggleDataSourceExpansion = async (dataSourceId, dataSourceType) => {
    const isCurrentlyExpanded = this.state.expandedDataSources[dataSourceId];
    
    // Toggle expansion state
    this.setState(prev => ({
      expandedDataSources: {
        ...prev.expandedDataSources,
        [dataSourceId]: !isCurrentlyExpanded,
      },
    }));

    // If expanding and schema not cached, fetch it
    if (!isCurrentlyExpanded && !this.state.dataSourceSchemas[dataSourceId]) {
      const schema = await this.fetchDataSourceSchema(dataSourceId, dataSourceType);
      this.setState(prev => ({
        dataSourceSchemas: {
          ...prev.dataSourceSchemas,
          [dataSourceId]: schema,
        },
      }));
    }
  };

  /**
   * ★★★ UPDATED: This function now fetches project data sources assigned to the project.
   * Only data sources that are explicitly assigned to the project will be available
   * for selection in the Primary and Secondary table windows.
   */
  fetchProjectQueries = async (projectId) => {
    if (!projectId) return [];

    try {
      // Fetch project items which includes assigned data sources
      const projectRes = await fetch(`/${orgSlug}/api/projects/${projectId}/items`, { credentials: 'same-origin' });
      if (!projectRes.ok) throw new Error(`HTTP ${projectRes.status}`);
      const projectData = await projectRes.json();

      const dataSources = projectData.data_sources || [];
      
      if (!Array.isArray(dataSources) || dataSources.length === 0) {
        console.warn('[TSQueryEditor] No data sources assigned to this project');
        return [];
      }

      // Map data sources to the format expected by the query editor
      // Each data source becomes a "query-like" object with tableName
      const dataSourceList = dataSources.map((ds) => {
        const dataSource = ds.data_source || ds;
        return {
          id: dataSource.id,
          name: dataSource.name,
          tableName: dataSource.name, // Use data source name as table name
          fields: [], // Will be populated when table is selected
          data_source_id: dataSource.id,
          type: dataSource.type,
        };
      });

      console.log('[TSQueryEditor] Project data sources loaded →', dataSourceList);
      return dataSourceList;
    } catch (err) {
      console.error('[TSQueryEditor] project data sources fetch failed →', err);
      return [];
    }
  }


  /**
   * When a query is **not** in any project we still need a minimal
   * queriesList so the Visual Builder can render a “Primary Table”.
   * This helper:
   * 1. loads the query       → /api/queries/:id
   * 2. infers its main table → extractTableName()
   * 3. seeds queriesList     → [{ id, name, tableName, fields: [] }]
   * 4. immediately selects it so preview columns/rows are fetched.
   */
  fetchUnassignedQuery = async (queryId) => {
    try {
      const qd = await fetch(`/${orgSlug}/api/queries/${queryId}`,
        { credentials: 'same-origin' }).then(r => r.json());
      const tblName = extractTableName(qd.query) || qd.name;
      const newEntry = { id: qd.id, name: qd.name, tableName: tblName, fields: [] };
      return [newEntry];
    } catch (err) {
      console.error('[TSQueryEditor] orphan-query bootstrap failed →', err);
      return [];
    }
  }


  handleProjectSelect = (e) => {
    if (e.detail?.projectId) this.initialize(e.detail.projectId);
  }

  /* ---------------- lifecycle ---------------- */
  /**
   * ★ NEW: Consolidated initialization logic.
   * This function is now the single entry point for loading all initial data.
   * It ensures that we have the full list of queries before attempting to
   * render any previews, which solves the race condition.
   */
  initialize = async (projectId) => {
    const { queryId } = this.state;

    // Fetch project data sources (does not block)
    this.fetchProjectDataSources(projectId);

    // Fetch the list of data sources from the project
    // NOTE: We no longer fetch queries - only data sources should appear in Primary/Secondary panes
    let dataSources = [];
    if (projectId) {
      dataSources = await this.fetchProjectQueries(projectId); // This now returns data sources, not queries
    }

    // Now that we have the complete list, set the state.
    this.setState({ queriesList: dataSources }, () => {
      // With the state updated, we can now safely trigger the preview fetches.
      const { leftTableName, rightTableName, selectedDataSourceId } = this.state;
      
      console.log('[initialize] Checking if should fetch preview:', {
        leftTableName,
        rightTableName,
        selectedDataSourceId,
        dataSources: dataSources.map(d => ({ id: d.id, name: d.name })),
      });
      
      // For database tables (e.g., foodmart.account), leftTableName won't match data source names
      // We need to check if we have a selectedDataSourceId and use that
      if (leftTableName) {
        const matchesDataSource = dataSources.some(q => (q.tableName || q.name) === leftTableName);
        const hasDataSourceId = selectedDataSourceId && dataSources.some(q => q.id === selectedDataSourceId);
        
        console.log('[initialize] leftTableName checks:', {
          matchesDataSource,
          hasDataSourceId,
          willCallHandleLeft: matchesDataSource || hasDataSourceId,
        });
        
        if (matchesDataSource || hasDataSourceId) {
          console.log('[initialize] Calling handleLeftTableSelect');
          this.handleLeftTableSelect(leftTableName);
        } else {
          console.log('[initialize] NOT calling handleLeftTableSelect - conditions not met');
        }
      }
      
      if (rightTableName) {
        const matchesDataSource = dataSources.some(q => (q.tableName || q.name) === rightTableName);
        const hasDataSourceId = selectedDataSourceId && dataSources.some(q => q.id === selectedDataSourceId);
        
        if (matchesDataSource || hasDataSourceId) {
          this.handleRightTableSelect(rightTableName);
        }
      }
    });
  }

  componentDidMount() {
    if (this.props.isNew) {
      this.setState({ initialized: true });
      const pid = this.getCurrentProjectId();
      if (pid) {
        this.initialize(pid);
      }
      return;
    }
    const { queryId } = this.state;

    if (queryId) {
      fetch(`/${orgSlug}/api/queries/${queryId}`)
        .then((r) => {
          if (!r.ok) throw new Error(r.statusText);
          return r.json();
        })
        .then((q) => {
          let saved = [];
          if (q.project_id != null) {
            saved = Array.isArray(q.project_id) ? q.project_id : [q.project_id];
          } else if (q.project_ids?.length) {
            saved = q.project_ids;
          } else if (q.projects?.length) {
            saved = q.projects.map(p => p.id);
          }
          
          // Restore visual builder state from options if available
          const newState = { selectedProjects: saved };
          if (q.options && typeof q.options === 'object') {
            if (q.options.leftTableName) newState.leftTableName = q.options.leftTableName;
            if (q.options.rightTableName) newState.rightTableName = q.options.rightTableName;
            if (q.options.joinClause) newState.joinClause = q.options.joinClause;
            if (q.options.joinType) newState.joinType = q.options.joinType;
            if (q.options.joinOperand) newState.joinOperand = q.options.joinOperand;
            if (q.options.selectedLeft) newState.selectedLeft = q.options.selectedLeft;
            if (q.options.selectedRight) newState.selectedRight = q.options.selectedRight;
            if (q.options.selectedDataSourceId) newState.selectedDataSourceId = q.options.selectedDataSourceId;
            
            // CRITICAL: Restore visualQuery BEFORE it gets overwritten by SQL parsing
            // If we have a saved visualQuery, use it instead of parsing the SQL
            if (q.options.visualQuery) {
              newState.visualQuery = q.options.visualQuery;
              console.log('[TSQueryEditor] Restored visualQuery from options:', q.options.visualQuery);
            } else {
              console.log('[TSQueryEditor] No saved visualQuery - will use parsed SQL');
            }
            
            if (q.options.rightTableName) newState.joinClicked = true;
            
            console.log('[TSQueryEditor] Restored visual builder state from options:', newState);
            
            // If we have saved field selections, build rqbAvailableFields
            if (newState.selectedLeft && newState.selectedLeft.length > 0) {
              const leftFields = newState.selectedLeft || [];
              const rightFields = newState.selectedRight || [];
              newState.rqbAvailableFields = [...leftFields, ...rightFields];
            }
          }
          
          // CRITICAL: Set state first, THEN initialize after state is set
          this.setState(newState, () => {
            const pid = this.getCurrentProjectId();
            this.initialize(pid);
            
            // Auto-execute disabled on component mount
            // The query.js service now forces fresh execution, so we don't need to execute here
            // This prevents interfering with field selection and initialization
          });
        })
        .catch(() => {
          // If query fetch fails, still try to initialize
          const pid = this.getCurrentProjectId();
          this.initialize(pid);
        });
    } else {
      // No queryId, just initialize normally
      const pid = this.getCurrentProjectId();
      this.initialize(pid);
    }

    document.addEventListener('project-selected', this.handleProjectSelect);
    window.addEventListener('resize', this.resizeAce);
  }

  componentDidUpdate() {} // No longer needed for initial load

  /**
   * Parses the current SQL text and re-initializes the visual builder state.
   * This is called when switching from the SQL editor back to the Visual editor.
   */
  reparseSqlForVisualEditor = () => {
    const { queryText, queriesList } = this.state;

    // 1. Parse all components from the current SQL text in the editor
    const newLeftTable = extractTableName(queryText);
    const newRightTable = extractJoinTableName(queryText);
    let newJoinClause = extractRawJoinClause(queryText);
    newJoinClause = stripWhere(newJoinClause);
    const newSelectedFields = extractSelectedFields(queryText);
    const newRuleTree = parseSQL(queryText, { listsAsArrays: true });

    // 2. Reset the visual state based on the parsed SQL.
    //    Clearing selections and previews forces a full refresh.
    this.setState({
      leftTableName: newLeftTable,
      rightTableName: newRightTable,
      joinClause: newJoinClause,
      initialSelectedColsRaw: newSelectedFields,
      visualQuery: newRuleTree,
      selectedLeft: [],
      selectedRight: [],
      leftPreview: { columns: [], rows: [] },
      rightPreview: { columns: [], rows: [] },
      joinClicked: !!newRightTable,
      mode: 'visual', // Switch the mode to 'visual'
    }, () => {
      // 3. After state is updated, trigger the preview fetching logic,
      //    which will in turn re-select the columns based on the new state.
      if (newLeftTable && queriesList.length > 0) {
        this.handleLeftTableSelect(newLeftTable);
      }
      if (newRightTable && queriesList.length > 0) {
        this.handleRightTableSelect(newRightTable);
      }
    });
    document.removeEventListener('mousemove', this.onHResize);
    document.removeEventListener('mouseup', this.stopHResize);
  }

  /**
   * Toggles the editor mode between 'visual' and 'sql'.
   */
  toggleEditorMode = () => {
    if (this.state.mode === 'visual') {
      this.setState({ mode: 'sql' }, this.resizeAce);
    } else {
      this.reparseSqlForVisualEditor();
    }
  }

  componentWillUnmount() {
    document.removeEventListener('mousemove', this.onVResize);
    document.removeEventListener('mouseup', this.stopVResize);
    document.removeEventListener('project-selected', this.handleProjectSelect);
    window.removeEventListener('resize', this.resizeAce);
  }

  static getDerivedStateFromProps(nextProps, prevState) {
    if (!nextProps.schema || isEqual(nextProps.schema, prevState.schema)) return null;
    const tokenCount = nextProps.schema.reduce((s, t) => s + t.columns.length, 0);
    return {
      keywords: keywordBuilder.buildKeywordsFromSchema(nextProps.schema),
      liveAutocompleteDisabled: tokenCount > 5000,
    };
  }


  /* ------------------ Resize SQL editor (height) ------------------ */
  startVResize = (e) => {
    e.preventDefault();
    this._resizing = true;
    document.addEventListener('mousemove', this.onVResize);
    document.addEventListener('mouseup', this.stopVResize);
  }

  onVResize = (e) => {
    if (!this._resizing) return;
    this.setState(
      prev => ({
        sqlEditorHeight: Math.max(120, prev.sqlEditorHeight + e.movementY),
      }),
      () => {
        localOptions.set('tsqeSqlHeight', this.state.sqlEditorHeight);
        this.resizeAce();
      },
    );
  }

  stopVResize = () => {
    this._resizing = false;
    document.removeEventListener('mousemove', this.onVResize);
    document.removeEventListener('mouseup', this.stopVResize);
  }

  /* ---------------- Ace helpers ---------------- */
  onAceLoad = (ed) => {
    ed.commands.bindKey('Cmd+L', null);
    ed.commands.bindKey('Ctrl+P', null);
    ed.commands.bindKey(
      { win: 'Ctrl+Shift+F', mac: 'Cmd+Shift+F' },
      this.formatQuery,
    );
    ed.commands.on('afterExec', (e) => {
      if (e.command.name === 'insertstring' && e.args === '.' && ed.completer) {
        ed.completer.showPopup(ed);
      }
    });

    QuerySnippet.query((snips) => {
      const mgr = ace.acequire('ace/snippets').snippetManager;
      const meta = { snippetText: '' };
      meta.snippets = mgr.parseSnippetFile(meta.snippetText);
      snips.forEach(s => meta.snippets.push(s.getSnippet()));
      mgr.register(meta.snippets, meta.scope);
    });

    this.props.listenForResize(() => ed.resize());
    this.props.listenForEditorCommand((_, cmd, ...args) => {
      if (cmd === 'focus') ed.focus();
      if (cmd === 'paste') {
        const [text] = args;
        ed.session.doc.replace(ed.selection.getRange(), text);
        const rng = ed.selection.getRange();
        this.updateQuery(ed.getValue());
        ed.selection.setRange(rng);
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
    this._bumpPreviewVersion();
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

  /* ------------------------------------------------------------------ */
  /* Misc helpers                                                       */
  /* ------------------------------------------------------------------ */
  openEditProjectsDialog = () => {
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

  saveProjects = (projects) => {
    fetch(`/${orgSlug}/api/available_projects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query_id: this.state.queryId, project_ids: projects }),
    })
      .then(() => notification.success('Projects updated'))
      .catch(() => notification.error('Update failed'));
  }

  resizeAce = () => {
    if (this.editorRef.current) {
      this.editorRef.current.editor.resize(true);
    }
  }


  /** Inserts plain text at the current Ace cursor position */
  insertAtCursor = (text) => {
    if (!this.editorRef.current) return;
    const editor = this.editorRef.current.editor;
    editor.session.doc.insert(editor.getCursorPosition(), text);
    editor.focus();
  }

  /** Update the live filter string for the schema browser */
  handleSchemaFilter = (e) => {
    this.setState({ schemaFilter: e.target.value });
  }

  /** Expand / collapse a table section in the schema browser */
  toggleTable = (tableName) => {
    this.setState(prev => ({
      expandedTables: {
        ...prev.expandedTables,
        [tableName]: !prev.expandedTables[tableName],
      },
    }));
  }

  /**
   * << NEW >> Unified handleExecute function with setTimeout to prevent race conditions.
   */
  handleExecute = () => {
    console.log('[TSQE] handleExecute triggered.');
    // Defer execution to allow the DOM to be ready and state to update
    setTimeout(() => {
      console.log('[TSQE] handleExecute: Running inside setTimeout.');
      const { isNew, dataSource, dataSources, executeQuery, updateQuery, queryExecuting } = this.props;
      const { selectedDataSourceId, queryText } = this.state;

      if (queryExecuting) {
        console.log('[TSQE] handleExecute: Aborted, query already executing.');
        return;
      }

      const sqlNow = this.editorRef.current
        ? this.editorRef.current.editor.getValue()
        : queryText;

      console.log('[TSQE] handleExecute: Query text to execute:', sqlNow);
      console.log('[TSQE] handleExecute: Updating parent query text.');
      updateQuery(sqlNow);

      const host = document.querySelector('.query-page-wrapper');
      const ng = window.angular;

      if (ng && host) {
        const scope = ng.element(host).scope();
        if (scope?.executeQuery) {
          console.log('[TSQE] handleExecute: Found Angular scope and executeQuery function.');
          scope.$applyAsync(() => {
            console.log('[TSQE] handleExecute: Inside $applyAsync. Updating scope properties.');
            scope.query.query = sqlNow;
            scope.isDirty = true; // Mark as dirty since we might be executing unsaved changes

            // If the query was just saved, this.state.isNew is now false.
            // If it's a truly new query that hasn't been saved, we need to provide the data source.
            if (this.state.isNew || isNew) { // Check both props and state for safety
              let dsId = selectedDataSourceId || (dataSource && dataSource.id);
              if (!dsId && dataSources && dataSources.length > 0) {
                dsId = dataSources[0].id;
              }
              if (dsId) {
                scope.query.data_source_id = dsId;
                console.log(`[TSQE] handleExecute: New query, setting data_source_id to ${dsId}`);
              } else {
                notification.error('Please select a data source before executing a new query.');
                console.error('[TSQE] handleExecute: Aborted, no data source for new query.');
                return;
              }
            }
            console.log('[TSQE] handleExecute: Calling scope.executeQuery().');
            scope.executeQuery();
          });
        } else {
          console.error('[TSQE] handleExecute: executeQuery function not found on Angular scope.');
          notification.error('Cannot find execute function. Please save the query and try again.');
        }
      } else {
        console.error('[TSQE] handleExecute: Angular execution context not found.');
        notification.error('Execution context not found. Please save the query and try again.');
      }
    }, 0); // A timeout of 0ms is enough to push it to the next event loop cycle.
  };

  /**
   * << NEW >> saveNewQuery function updated to dispatch an event instead of navigating.
   */
  /**
   * Get visual builder state to save in query options
   */
  getVisualBuilderState = () => {
    // Clean up visualQuery by removing empty/invalid rules
    let cleanedVisualQuery = this.state.visualQuery;
    if (cleanedVisualQuery && cleanedVisualQuery.rules) {
      const validRules = cleanedVisualQuery.rules.filter(
        r => r.field && r.operator && r.value !== null && r.value !== undefined && r.value !== ''
      );
      cleanedVisualQuery = {
        ...cleanedVisualQuery,
        rules: validRules
      };
      console.log('[getVisualBuilderState] Cleaned visualQuery - removed', 
        this.state.visualQuery.rules.length - validRules.length, 'invalid rules');
    }
    
    const state = {
      leftTableName: this.state.leftTableName,
      rightTableName: this.state.rightTableName,
      joinClause: this.state.joinClause,
      joinType: this.state.joinType,
      joinOperand: this.state.joinOperand,
      selectedLeft: this.state.selectedLeft,
      selectedRight: this.state.selectedRight,
      selectedDataSourceId: this.state.selectedDataSourceId,
      visualQuery: cleanedVisualQuery, // Save cleaned filter rules
    };
    console.log('[getVisualBuilderState] Saving visualQuery:', cleanedVisualQuery);
    return state;
  };

  /**
   * Save existing query with visual builder state
   */
  saveExistingQuery = () => {
    const { saveQuery } = this.props;
    const { queryId, queryText } = this.state;
    
    if (!queryId || !saveQuery) {
      console.error('[TSQueryEditor] Cannot save: missing queryId or saveQuery function');
      return;
    }

    // Update query options with visual builder state before saving
    const visualBuilderState = this.getVisualBuilderState();
    
    console.log('[saveExistingQuery] Saving visual builder state:', visualBuilderState);
    console.log('[saveExistingQuery] selectedLeft:', visualBuilderState.selectedLeft);
    console.log('[saveExistingQuery] selectedRight:', visualBuilderState.selectedRight);
    console.log('[saveExistingQuery] queryText to save:', queryText);
    console.log('[saveExistingQuery] queryText length:', queryText?.length);
    console.log('[saveExistingQuery] selectedDataSourceId:', this.state.selectedDataSourceId);
    console.log('[saveExistingQuery] leftTableName:', this.state.leftTableName);
    console.log('[saveExistingQuery] queriesList:', this.state.queriesList);
    
    // Save both the query text AND the visual builder options in one call
    // This prevents the parent's saveQuery from overwriting our options
    const payload = {
      query: queryText,
      options: visualBuilderState,
    };
    
    // Include data_source_id if we have one selected
    if (this.state.selectedDataSourceId) {
      payload.data_source_id = this.state.selectedDataSourceId;
      console.log('[saveExistingQuery] ✓ Including data_source_id:', this.state.selectedDataSourceId);
    } else {
      console.warn('[saveExistingQuery] ✗ NO selectedDataSourceId - trying to find from leftTableName');
      // Try to find data_source_id from leftTableName
      const leftEntry = this.state.queriesList.find(
        q => (q.tableName || q.name) === this.state.leftTableName
      );
      if (leftEntry && leftEntry.data_source_id) {
        payload.data_source_id = leftEntry.data_source_id;
        console.log('[saveExistingQuery] ✓ Found data_source_id from leftTableName:', leftEntry.data_source_id);
      } else {
        console.error('[saveExistingQuery] ✗ Could not find data_source_id - query will not auto-add to project!');
      }
    }
    
    console.log('[saveExistingQuery] Full payload:', JSON.stringify(payload, null, 2));
    
    fetch(`/${orgSlug}/api/queries/${queryId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    })
    .then((response) => {
      console.log('[saveExistingQuery] API response status:', response.status);
      if (!response.ok) {
        throw new Error(`API returned ${response.status}`);
      }
      return response.json();
    })
    .then((data) => {
      console.log('[saveExistingQuery] API response data:', data);
      console.log('[saveExistingQuery] Saved options in response:', data.options);
      console.log('[saveExistingQuery] Saved selectedLeft in response:', data.options?.selectedLeft);
      
      // Verify the save was successful
      if (data.options && data.options.selectedLeft) {
        console.log('[saveExistingQuery] ✓ Options saved successfully with', data.options.selectedLeft.length, 'fields');
      } else {
        console.error('[saveExistingQuery] ✗ Options NOT saved correctly!');
      }
      
      // Update the parent component's query object with the new options AND query text
      // This ensures that if the parent saves again, it has the correct data
      if (this.props.updateSelectedQuery && typeof this.props.updateSelectedQuery === 'function') {
        console.log('[saveExistingQuery] Updating parent query object with new options and query text');
        this.props.updateSelectedQuery({ 
          query: queryText,
          options: visualBuilderState 
        });
      }
      
      // DON'T call the parent's saveQuery - we've already saved everything
      // The parent's saveQuery would make another API call that might use stale data
      console.log('[saveExistingQuery] NOT calling parent saveQuery - already saved to API');
      
      // Show success notification
      notification.success('Query saved successfully');
      
      // Update the Angular scope to mark query as not dirty AND update the query text
      // This ensures the parent has the latest query text for future operations
      if (window.angular) {
        const element = document.querySelector('[ng-controller="QueryViewCtrl"]');
        if (element) {
          const scope = window.angular.element(element).scope();
          if (scope) {
            scope.$applyAsync(() => {
              scope.isDirty = false;
              // Update the query text in the Angular scope
              if (scope.query) {
                scope.query.query = queryText;
                scope.query.options = visualBuilderState;
                console.log('[saveExistingQuery] Updated Angular scope with new query text and options');
              }
              
              // Execute the query to update the cached results
              // This ensures that when the query is reopened, it shows the correct data
              if (scope.executeQuery && typeof scope.executeQuery === 'function') {
                console.log('[saveExistingQuery] Executing query to update cached results');
                scope.executeQuery();
              }
              
              console.log('[saveExistingQuery] Cleared isDirty flag in Angular scope');
            });
          }
        }
      }
      
      // Dispatch an event to notify that the query was saved
      // This allows the parent to update its UI without making another API call
      const event = new CustomEvent('query-saved', { 
        detail: { queryId, query: data } 
      });
      document.dispatchEvent(event);
    })
    .catch((err) => {
      console.error('[TSQueryEditor] Error saving visual builder state:', err);
      // Still try to save the query even if options update fails
      saveQuery();
    });
  };

  saveNewQuery = async () => {
    const { projectId, dataSource, dataSources = [] } = this.props;
    const dsId = this.state.selectedDataSourceId || (dataSource && dataSource.id) || (dataSources[0] && dataSources[0].id);

    if (!dsId) {
      notification.error('No data source available – please select or open a table first.');
      return;
    }

    // Save visual builder state in options
    const visualBuilderState = this.getVisualBuilderState();

    const payload = {
      name: this.state.name || 'New Query',
      query: this.state.queryText,
      project_id: projectId != null ? [Number(projectId)] : null, // ensure array or null
      data_source_id: dsId,
      options: visualBuilderState, // Store visual builder state
    };

    try {
      const resp = await fetch(`/${orgSlug}/api/queries`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        const errText = await resp.text();
        throw new Error(errText || resp.statusText);
      }
      const q = await resp.json();
      if (!q.id) throw new Error('No ID returned from server');

      notification.success('Query saved.');

      // Dispatch an event that the parent component (TableScopeHome) can listen for.
      document.dispatchEvent(new CustomEvent('new-query-saved', { detail: { queryId: q.id } }));
    } catch (err) {
      console.error('saveNewQuery error', err);
      notification.error(`Failed to save the new query: ${err.message || err}`);
    }
  };

  // << NEW >> Handler for the data source dropdown
  handleDataSourceChange = (dsId) => {
    this.setState({ selectedDataSourceId: dsId });
    this.props.updateDataSource(dsId); // Call the original prop to update Angular
  }

  /* ---------------- table selection handlers ---------------- */

  /**
   * ★ NEW: Handles clicks on the primary table checkboxes.
   * This function resets the entire join configuration before selecting the new primary table.
   */
  handlePrimaryTableChange = (tableName) => {
    this.setState({
      rightTableName: '',
      joinClause: '',
      selectedRight: [],
      rightPreview: { columns: [], rows: [] },
      joinClicked: false,
    }, () => {
      this.handleLeftTableSelect(tableName);
    });
  }

  /**
   * ★ UPDATED: This function is now non-destructive.
   * It only sets state relevant to the left table and fetches its preview.
   * It clears `selectedLeft` and relies on `_evaluateAndFinalizeSelections` to repopulate it.
   */
  handleLeftTableSelect = (tableName) => {
    this._bumpPreviewVersion();
    if (!this.state.queriesList.length) return;
    
    // Try to find entry in queriesList
    let leftEntry = this.state.queriesList.find(
      q => (q.tableName || q.name) === tableName,
    );
    
    // If not found, it might be a table from a schema
    // Create a virtual entry using the selected data source ID
    if (!leftEntry && this.state.selectedDataSourceId) {
      leftEntry = {
        id: this.state.selectedDataSourceId,
        name: tableName,
        tableName: tableName,
        data_source_id: this.state.selectedDataSourceId,
        fields: [],
      };
      console.log(`[handleLeftTableSelect] Created virtual entry for schema table: ${tableName}`);
    }
    
    if (!leftEntry || !leftEntry.id) {
      console.log(`[handleLeftTableSelect] No entry or no ID found for tableName='${tableName}'`);
      return;
    }
    console.log(`[handleLeftTableSelect] tableName='${tableName}', queryId=${leftEntry.id}`);
    console.log(`[handleLeftTableSelect] Current selectedLeft:`, this.state.selectedLeft);

    this.setState(
      prevState => {
        const preservedLeft = prevState.selectedLeft && prevState.selectedLeft.length > 0 ? prevState.selectedLeft : [];
        console.log(`[handleLeftTableSelect] Preserving selectedLeft:`, preservedLeft);
        return {
          leftTableName: tableName,
          selectedLeft: preservedLeft,
          leftPreview: { columns: [], rows: [] },
        };
      },
      () => {
        console.log(`[handleLeftTableSelect] After setState, selectedLeft:`, this.state.selectedLeft);
        this.fetchPreviewById(leftEntry.id, 'left');
      },
    );
  }

  /**
   * ★ UPDATED: This function is simplified and non-destructive.
   * It only sets state for the right table and fetches its preview.
   * It clears `selectedRight` and relies on `_evaluateAndFinalizeSelections` to repopulate it.
   */
  handleRightTableSelect = (tableName) => {
    // Try to find entry in queriesList
    let rightEntry = this.state.queriesList.find(
      q => (q.tableName || q.name) === tableName,
    );
    
    // If not found, it might be a table from a schema
    // Create a virtual entry using the selected data source ID
    if (!rightEntry && this.state.selectedDataSourceId) {
      rightEntry = {
        id: this.state.selectedDataSourceId,
        name: tableName,
        tableName: tableName,
        data_source_id: this.state.selectedDataSourceId,
        fields: [],
      };
      console.log(`[handleRightTableSelect] Created virtual entry for schema table: ${tableName}`);
    }
    
    if (!rightEntry || !rightEntry.id) {
      console.log(`[handleRightTableSelect] No entry or no ID found for tableName='${tableName}'`);
      return;
    }
    console.log(`[handleRightTableSelect] tableName='${tableName}', queryId=${rightEntry.id}`);

    this.setState(
      prevState => ({
        rightTableName: tableName,
        // Only clear selection if we don't have existing selections (from restored state)
        selectedRight: prevState.selectedRight && prevState.selectedRight.length > 0 ? prevState.selectedRight : [],
        rightPreview: { columns: [], rows: [] },
        previewReady: { ...prevState.previewReady, right: false }, // Only reset the right side
      }),
      () => {
        // Fetch preview which will populate columns and trigger SQL generation
        this.fetchPreviewById(rightEntry.id, 'right');
      },
    );
  }

  /* ---------------- visual builder handlers ---------------- */
  handleJoinClick = () => {
    this.setState({ joinClicked: true });
  }


  /**
   * Fetches the first 5 rows of a query's result set for preview purposes.
   * This function ensures a fresh, unfiltered preview by fetching the original
   * query's SQL, wrapping it in a `LIMIT 5` clause, and executing it as a
   * new ad-hoc query. This completely decouples the preview from the state
   * of the main visual query builder.
   */
  fetchPreviewById = async (queryId, side) => {
    console.log(`[fetchPreviewById] called with queryId=${queryId}, side='${side}'`);

    try {
      // Find the entry in queriesList (which now contains data sources)
      const entry = this.state.queriesList.find(q => q.id === queryId);
      if (!entry) {
        throw new Error(`No entry found for ID ${queryId}`);
      }

      // Determine if this is a data source or a query
      const isDataSource = entry.data_source_id !== undefined;
      let dataSourceId;
      let tableNameForPreview;

      if (isDataSource) {
        // This is a data source entry
        dataSourceId = entry.data_source_id || entry.id;
        // Use the table name from state (which could be a schema table or the data source name itself)
        tableNameForPreview = side === 'left' ? this.state.leftTableName : this.state.rightTableName;
        console.log(`[fetchPreviewById] Using data source: ${tableNameForPreview} (ID: ${dataSourceId})`);
        console.log(`[fetchPreviewById] Entry details:`, entry);
        
        // Set the selected data source ID
        this.setState({ selectedDataSourceId: dataSourceId });
      } else {
        // This is a query entry (legacy support)
        const queryDetailsRes = await fetch(`/${orgSlug}/api/queries/${queryId}`, { credentials: 'same-origin' });
        if (!queryDetailsRes.ok) {
          throw new Error(`Failed to fetch query details for ID ${queryId}`);
        }
        const queryDetails = await queryDetailsRes.json();
        const originalSql = queryDetails.query;
        dataSourceId = queryDetails.data_source_id;
        
        // Set the selected data source ID
        this.setState({ selectedDataSourceId: dataSourceId });

        tableNameForPreview = side === 'left'
          ? (this.state.leftTableName || extractTableName(originalSql))
          : (this.state.rightTableName || extractJoinTableName(originalSql));
      }

      // Build the preview SQL
      // Ensure table name is uppercase to match VDB view names
      const normalizedTableName = tableNameForPreview.toUpperCase();
      const previewSql = `SELECT * FROM ${normalizedTableName} LIMIT 5`;
      console.log(`[fetchPreviewById] Original table name: ${tableNameForPreview}`);
      console.log(`[fetchPreviewById] Normalized table name: ${normalizedTableName}`);
      console.log(`[fetchPreviewById] Preview SQL: ${previewSql}`);

      // Execute this ad-hoc query
      // Include query_id if available so backend can determine project context for VDB routing
      const adhocUrl = `/${orgSlug}/api/query_results`;
      const requestBody = {
        data_source_id: dataSourceId,
        query: previewSql,
        max_age: 0, // Force execution
      };
      
      // Add query_id if this is an existing query (not a new query)
      if (this.state.queryId) {
        requestBody.query_id = this.state.queryId;
        console.log(`[fetchPreviewById] Including query_id ${this.state.queryId} for project context`);
      }
      
      const adhocRes = await fetch(adhocUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      });

      if (!adhocRes.ok) {
        throw new Error(`HTTP ${adhocRes.status} for ad-hoc preview execution`);
      }
      let json = await adhocRes.json();

      // 4. If Redash returned a job, poll for the result
      if (json.job) {
        console.log('[fetchPreviewById] Got a job for ad-hoc query, polling for result...', json.job.id);
        json = await pollJob(json.job.id);
      }

      if (!json.query_result) {
        throw new Error('Preview data is missing the `query_result` key.');
      }
      const data = json.query_result.data;

      /* ── Get all possible column names for the preview table ──────────────── */
      const queryEntry = this.state.queriesList.find(q => q.id === queryId);
      const tableName = side === 'left' ? this.state.leftTableName : this.state.rightTableName;
      let allFieldNames = [];
      const normalizeTbl = s => (s || '').toString().split('.').pop().replace(/[`"\[\]]/g, '')
        .toLowerCase();
      const schemaEntry = (this.props.schema || []).find(t => normalizeTbl(t.name) === normalizeTbl(tableName) || normalizeTbl(tableName).endsWith(normalizeTbl(t.name)));
      if (schemaEntry && Array.isArray(schemaEntry.columns)) {
        allFieldNames = schemaEntry.columns.map(col => (typeof col === 'string' ? col : col.name));
      }
      if (!allFieldNames.length && queryEntry && Array.isArray(queryEntry.fields)) {
        allFieldNames = queryEntry.fields.slice();
      }
      const keysInRows = (data.rows || []).reduce((acc, r) => acc.concat(Object.keys(r)), []);
      allFieldNames = [...new Set([...allFieldNames, ...keysInRows])];
      console.log('[fetchPreviewById] all fields after schema merge:', allFieldNames);

      /* ------------------------------------------------------------------
       * PATCH queriesList – but **only** if the column list is different,
       * otherwise skip setState to prevent the re-render loop
       * ------------------------------------------------------------------ */
      this.setState((prev) => {
        const hit = prev.queriesList.find(q => q.id === queryId);
        if (!hit) return null; // first time ⇒ update
        const sameLen = hit.fields.length === allFieldNames.length;
        const sameSeq = sameLen && hit.fields.every((c, i) => c === allFieldNames[i]);
        if (sameSeq) return null; // nothing new ⇒ no update
        return {
          queriesList: prev.queriesList.map(q => (q.id === queryId ? { ...q, fields: allFieldNames } : q)),
        };
      });


      /* ── Build column and row objects for the DataGrid ────────────────────── */
      const columns = allFieldNames.map(f => ({
        field: f,
        headerName: f,
        flex: 1,
        minWidth: 100,
        sortable: false,
      }));

      const rows = (data.rows || []).slice(0, 5).map((rowObj, idx) => {
        const fullRow = { id: idx };
        allFieldNames.forEach((col) => {
          fullRow[col] = rowObj[col] !== undefined ? rowObj[col] : null;
        });
        return fullRow;
      });

      /* ── Update component state with the new preview data ─────────────────── */
      if (side === 'left') {
        this.setState({ leftPreview: { columns, rows }, previewReady: { ...this.state.previewReady, left: true } }, this._evaluateAndFinalizeSelections);
      } else {
        this.setState({ rightPreview: { columns, rows }, previewReady: { ...this.state.previewReady, right: true } }, this._evaluateAndFinalizeSelections);
      }

      /* After preview loads, trigger resize for auto height */
      setTimeout(() => window.dispatchEvent(new Event('resize')), 100);
    } catch (err) {
      console.error('[fetchPreviewById] error →', err);
      notification.error(err.message || 'Failed to load preview data.');
      if (side === 'left') this.setState({ leftPreview: { columns: [], rows: [] } });
      else this.setState({ rightPreview: { columns: [], rows: [] } });
    }
  }

  /**
   * ★ This function is the single source of truth for setting column selections.
   * It runs each time a preview finishes loading and checks if all necessary
   * previews are ready. If so, it calculates the selections deterministically
   * and updates the state, forcing a re-render of the grids.
   */
  _evaluateAndFinalizeSelections = () => {
    const {
      previewReady,
      joinClicked,
      rightTableName,
      leftTableName,
      leftPreview,
      rightPreview,
      initialSelectedColsRaw,
      queryText,
      joinClause,
      selectedLeft,
      selectedRight,
    } = this.state;

    console.log('[_evaluateAndFinalizeSelections] Called with:', {
      previewReady,
      leftTableName,
      rightTableName,
      selectedLeft,
      selectedRight,
      leftPreviewCols: leftPreview?.columns?.length,
    });

    // Exit if the necessary previews aren't loaded yet.
    if (!previewReady.left || (joinClicked && rightTableName && !previewReady.right)) {
      console.log('[_evaluateAndFinalizeSelections] Previews not ready, exiting');
      return;
    }

    // Both previews are ready. Time to calculate selections.
    const rawSel = initialSelectedColsRaw.length > 0
      ? initialSelectedColsRaw
      : extractSelectedFields(queryText);

    const fq = (tbl, cols) => (tbl ? cols.map(c => `${tbl}.${c}`) : []);
    const leftCols = (leftPreview?.columns || []).map(c => c.field);
    const rightCols = (rightPreview?.columns || []).map(c => c.field);

    const leftAll = fq(leftTableName, leftCols);
    const rightAll = fq(rightTableName, rightCols);

    console.log('[_evaluateAndFinalizeSelections] leftAll:', leftAll);
    console.log('[_evaluateAndFinalizeSelections] Current selectedLeft:', selectedLeft);

    // If we already have selections (from restored state), keep them
    // Otherwise, select all columns by default, or filter to match explicitly selected ones
    let newSelectedLeft, newSelectedRight;
    
    if (selectedLeft && selectedLeft.length > 0) {
      // We have restored selections, validate they match available columns
      console.log('[_evaluateAndFinalizeSelections] Validating restored selections');
      
      // Filter to only include columns that exist in the preview
      const validLeft = selectedLeft.filter(sel => {
        // Check if the selection matches any available column (with or without table prefix)
        const shortName = sel.split('.').pop();
        return leftAll.some(avail => avail === sel || avail.endsWith(`.${shortName}`));
      });
      
      console.log('[_evaluateAndFinalizeSelections] Valid restored selections:', validLeft);
      
      // If we have valid restored selections, use them; otherwise calculate new ones
      if (validLeft.length > 0) {
        newSelectedLeft = validLeft;
        newSelectedRight = selectedRight || [];
      } else {
        // No valid restored selections, select all
        console.log('[_evaluateAndFinalizeSelections] No valid restored selections, selecting all');
        newSelectedLeft = leftAll;
        newSelectedRight = rightTableName ? rightAll : [];
      }
    } else {
      // Calculate selections from SQL or select all
      console.log('[_evaluateAndFinalizeSelections] Calculating new selections');
      const choose = list => (rawSel.length
        ? list.filter(f => rawSel.includes(f) || rawSel.includes(f.split('.').pop()))
        : list); // Return all columns by default so they appear as field names, not SELECT *

      newSelectedLeft = choose(leftAll);
      newSelectedRight = rightTableName ? choose(rightAll) : [];
    }

    console.log('[_evaluateAndFinalizeSelections] Final newSelectedLeft:', newSelectedLeft);

    // Now, update the state. Incrementing previewVersion will force the grids to re-render.
    this.setState(
      prevState => ({
        selectedLeft: newSelectedLeft,
        selectedRight: newSelectedRight,
        previewVersion: prevState.previewVersion + 1, // Force re-render
      }),
      () => {
        // After state is set, update the SQL query itself.
        this.handleJoinChange({
          leftTableName,
          rightTableName,
          joinClause,
          selectedLeftCols: newSelectedLeft,
          selectedRightCols: newSelectedRight,
          leftAllFields: leftAll,
          rightAllFields: rightAll,
        });
      },
    );
  };


  /** ----------------------------------------------------------------
   * Completely rebuild (or patch) the SQL text shown in the top
   * preview when Visual-Builder is active.
   * • SELECT list now keeps FULLY-QUALIFIED column names
   * so “Name” → “MyCompany.SalesJournal2020_XLSX.Name”.
   * • Aliases left intact (no stripping).
   * ---------------------------------------------------------------- */
  /* ------------------------------------------------------------------ */
  /* Completely rebuild (or patch) the SQL text shown in Visual Builder */
  /* ------------------------------------------------------------------ */
  rebuildVisualSQL = (ruleTree = this.state.visualQuery, returnOnly = false) => {
    const {
      leftTableName,
      rightTableName,
      joinClause = '',
      selectedLeft = [],
      selectedRight = [],
      queryText: existingSQL = '',
    } = this.state;

    const baseSQLNoWhere = existingSQL.split(/\bWHERE\b/i)[0];
    /* helper – pull whatever was after SELECT … before FROM …            */
    const extractSelect = (sql) => {
      const m = sql.match(/select\s+([\s\S]*?)\s+from\b/i);
      return m ? m[1].trim() : '*';
    };

    /* ────────────────────── 1)  Build SELECT list ─────────────────────── */

    const allFields = this.state.rqbAvailableFields || [];

    const getAllFor = tbl => (
      tbl
        ? allFields
          .filter(f => f.startsWith(`${tbl}.`))
          .map(f => f.split('.').slice(1).join('.')) // drop “tbl.” prefix
        : []
    );

    const leftAll = getAllFor(leftTableName);
    const rightAll = getAllFor(rightTableName);

    const fmt = (tbl, picks) => {
      if (!tbl || picks.length === 0) return [];
      return picks.map(c => (c.includes('.') ? c : `${tbl}.${c}`));
    };

    const selectParts = [
      ...fmt(leftTableName, selectedLeft),
      ...fmt(rightTableName, selectedRight),
    ];

    /* if picks haven’t arrived yet keep whatever SELECT list is already
     in the SQL (avoids an unwanted “*” overwrite on first render)       */
    const selectSQL = selectParts.length
      ? selectParts.join(', ')
      : '';

    /* ────────────────────── 2)  WHERE clause (unchanged) ──────────────── */

    let whereSQL = '';
    if (ruleTree?.rules?.length) {
      const valid = ruleTree.rules.filter(
        r => r.field && r.operator && r.value !== undefined && r.value !== null,
      );
      if (valid.length) {
        try {
          whereSQL = formatQuery(
            { combinator: ruleTree.combinator, rules: valid },
            { format: 'sql' },
          );
        } catch { /* ignore formatting errors */ }
      }
    }

    /* ────────────────────── 3)  Stitch it together  ───────────────────── */

    // Don't build SQL if no table is selected
    if (!leftTableName) {
      console.log('[rebuildVisualSQL] No leftTableName, skipping SQL generation');
      if (returnOnly) {
        return '';
      }
      return;
    }

    // Only generate SQL if we have fields selected
    if (!selectSQL || !selectSQL.trim()) {
      console.log('[rebuildVisualSQL] No fields selected, skipping SQL generation');
      if (returnOnly) {
        return '';
      }
      return;
    }

    // Ensure table names are uppercase to match VDB view names
    const normalizedLeftTable = leftTableName.toUpperCase();
    const built = `
    SELECT ${selectSQL}
      FROM ${normalizedLeftTable}
      ${joinClause}
      ${whereSQL ? ('WHERE ' + whereSQL) : ''}
  `
      .replace(/\s{2,}/g, ' ') // squeeze whitespace
      .trim();

    console.log('[rebuildVisualSQL] Generated SQL:', built);
    console.log('[rebuildVisualSQL] leftTableName:', leftTableName);
    console.log('[rebuildVisualSQL] selectSQL:', selectSQL);

    if (returnOnly) {
      return built;
    }
    this.updateQuery(built);
  }
  /* ------------------------------------------------------------------ */


  handleFilterChange = (ruleTree) => {
    this.setState({ visualQuery: ruleTree }, () => {
      this.rebuildVisualSQL(ruleTree);
      // Auto-execute when filter changes to show results immediately
      console.log('[handleFilterChange] Filter changed - auto-executing query');
      setTimeout(() => {
        this.handleExecute();
      }, 300); // Small delay to ensure SQL is rebuilt
    });
  };

  /**
   * Sync state from <JoinBuilder>.
   *
   * ──────────────────────────────────────────────────────────
   * ❶  NO MORE auto-generation when the user merely clicks
   * columns. We accept the JOIN clause only if JoinBuilder
   * supplies a non-empty string (meaning both operands were
   * chosen in the Relation Properties section).
   *
   * ❷  joinType / joinOperand are still bubbled up so the user’s
   * dropdown choices are preserved, but they do not trigger a
   * clause until JoinBuilder passes back `joinClause`.
   * ──────────────────────────────────────────────────────────
   */
  handleJoinChange = ({
    leftTableName,
    rightTableName,
    joinType = this.state.joinType,
    joinOperand = this.state.joinOperand,
    joinClause = '', // possibly empty
    selectedLeftCols = [],
    selectedRightCols = [],
    leftAllFields = [],
    rightAllFields = [],
  }) => {
  /* merge with previous selections -------------------------- */
    const {
      selectedLeft: prevLeft,
      selectedRight: prevRight,
      joinClause: prevJoin,
      leftTableName: prevLeftTable,
      rightTableName: prevRightTable,
    } = this.state;

    const newLeftCols = selectedLeftCols.length ? selectedLeftCols : prevLeft;
    const newRightCols = selectedRightCols.length ? selectedRightCols : prevRight;

    const newLeftTable = leftTableName || prevLeftTable;
    const newRightTable = rightTableName || prevRightTable;

    /* accept a JOIN only if builder sent one ------------------- */
    const nextJoin = joinClause.trim() || prevJoin;

    /* diagnostics ---------------------------------------------- */
    console.log('[RelationProps] leftTable=', newLeftTable,
      'leftCols=', JSON.stringify(newLeftCols));
    console.log('[RelationProps] rightTable=', newRightTable,
      'rightCols=', JSON.stringify(newRightCols));
    console.log('[JoinBuilder]  newJoinClause =', `"${nextJoin}"`);

    /* commit to state ------------------------------------------ */
    this.setState(
      {
        leftTableName: newLeftTable,
        rightTableName: newRightTable,
        joinType,
        joinOperand,
        joinClause: nextJoin,
        selectedLeft: newLeftCols,
        selectedRight: newRightCols,
        rqbAvailableFields: [...leftAllFields, ...rightAllFields],
      },
      () => {
        // AGGRESSIVE: Always rebuild SQL when handleJoinChange is called
        // This ensures field selections are immediately reflected in the SQL
        console.log('[handleJoinChange] ALWAYS rebuilding SQL with current state:', {
          newLeftTable,
          newRightTable,
          newLeftCols: newLeftCols.length,
          newRightCols: newRightCols.length,
        });
        
        this.rebuildVisualSQL(this.state.visualQuery);
      },
    );
  }

  /* ───────────────────────────────────────────────────────────── */
  /* ★ NEW — clearJoin handler                                      */
  /* ───────────────────────────────────────────────────────────── */
  handleClearJoin = () => {
    this.setState(
      {
        joinClause: '',
        rightTableName: '',
        selectedRight: [],
        joinClicked: false,
      },
      () => {
        this.rebuildVisualSQL(this.state.visualQuery);
      },
    );
  }


  addRuleBelow = () => {
    this.setState(
      (state) => {
        const tree = state.visualQuery || { combinator: 'and', rules: [] };
        const rules = Array.isArray(tree.rules) ? [...tree.rules] : [];
        rules.push({ field: null, operator: null, value: null });
        return { visualQuery: { ...tree, rules } };
      },
      () => this.rebuildVisualSQL(this.state.visualQuery),
    );
  }

  // Toggle a primary column from preview header click
  togglePrimaryColumn = (field) => {
    const {
      leftTableName,
      selectedLeft,
      selectedRight,
      joinClause,
      rqbAvailableFields,
      rightTableName,
    } = this.state;
    const fullKey = `${leftTableName}.${field}`;
    let newSelectedLeft;
    if (selectedLeft.includes(fullKey)) {
      newSelectedLeft = selectedLeft.filter(k => k !== fullKey);
    } else {
      newSelectedLeft = [...selectedLeft, fullKey];
    }
    const leftAllFields = rqbAvailableFields.filter(k => k.startsWith(`${leftTableName}.`));
    const rightAllFields = rqbAvailableFields.filter(k => k.startsWith(`${rightTableName}.`));
    this.handleJoinChange({
      leftTableName,
      rightTableName,
      joinClause,
      selectedLeftCols: newSelectedLeft,
      selectedRightCols: selectedRight,
      leftAllFields,
      rightAllFields,
    });
  };

  // Toggle a secondary column from preview header click
  toggleSecondaryColumn = (field) => {
    const {
      rightTableName,
      selectedLeft,
      selectedRight,
      joinClause,
      rqbAvailableFields,
      leftTableName,
    } = this.state;
    const fullKey = `${rightTableName}.${field}`;
    let newSelectedRight;
    if (selectedRight.includes(fullKey)) {
      newSelectedRight = selectedRight.filter(k => k !== fullKey);
    } else {
      newSelectedRight = [...selectedRight, fullKey];
    }
    const leftAllFields = rqbAvailableFields.filter(k => k.startsWith(`${leftTableName}.`));
    const rightAllFields = rqbAvailableFields.filter(k => k.startsWith(`${rightTableName}.`));
    this.handleJoinChange({
      leftTableName,
      rightTableName,
      joinClause,
      selectedLeftCols: selectedLeft,
      selectedRightCols: newSelectedRight,
      leftAllFields,
      rightAllFields,
    });
  };

  /* ------------------------------------------------------------------ */
  /* Render                                                             */
  /* ------------------------------------------------------------------ */

  _bumpPreviewVersion = () => {
    this.setState({
      previewReady: { left: false, right: false },
    });
  };


  render() {
    const {
      canExecuteQuery,
      queryExecuting,
      addNewParameter,
      saveQuery,
      isDirty,
      canEdit,
      isNew,
      dataSources,
      dataSource,
      schema,
    } = this.props;
    const visibleDs = (this.state && this.state.projectDataSources && this.state.projectDataSources.length)
      ? this.state.projectDataSources
      : (dataSources || []);

    const {
      mode,
      queryText,
      autocompleteQuery,
      liveAutocompleteDisabled,
      visualQuery,
      queriesList,
      queryId,
      leftTableName,
      rightTableName,
      leftPreview,
      rightPreview,
      selectedLeft,
      selectedRight,
      joinClicked,
      joinClause,
      joinType, // Pass to JoinBuilder
      joinOperand, // Pass to JoinBuilder
      localCanExecute,
    } = this.state;

    // ★ NEW: Parse the join clause to extract parts for the JoinBuilder
    let initialLeftCol = '';
    let initialRightCol = '';
    let initialJoinOp = joinOperand; // Default to state
    let initialJoinType = joinType; // Default to state

    if (joinClause) {
      const onMatch = joinClause.match(/on\s+([^\s]+)\s*([=<>!]+)\s*([^\s]+)/i);
      if (onMatch) {
        [, initialLeftCol, initialJoinOp, initialRightCol] = onMatch;
      }
      const typeMatch = joinClause.match(/^(inner|left|right|full)/i);
      if (typeMatch) {
        initialJoinType = typeMatch[1].toUpperCase();
      }
    }


    /* Schema-browser panel (left side when in SQL mode) */
    const renderSchemaBrowser = () => {
    // Current schema from props
      const currentSchema = [...(schema || [])];

      // Add selected left and right tables to the schema if they are not already there
      const { leftTableName, rightTableName, queriesList, joinClause } = this.state;

      // Only add joined tables to schema browser if in SQL mode AND a join exists
      if (mode === 'sql' && joinClause) {
        const normalizeTblName = name => (name || '').toString().toLowerCase();

        // Ensure leftTableName is in the schema if it's not already
        if (leftTableName && !currentSchema.some(t => normalizeTblName(t.name) === normalizeTblName(leftTableName))) {
          const leftQueryEntry = queriesList.find(q => normalizeTblName(q.tableName || q.name) === normalizeTblName(leftTableName));
          if (leftQueryEntry) {
            currentSchema.push({
              name: leftTableName,
              columns: leftQueryEntry.fields || [], // Use fields from queriesList if available
            });
          }
        }

        // Ensure rightTableName is in the schema if it's not already
        if (rightTableName && !currentSchema.some(t => normalizeTblName(t.name) === normalizeTblName(rightTableName))) {
          const rightQueryEntry = queriesList.find(q => normalizeTblName(q.tableName || q.name) === normalizeTblName(rightTableName));
          if (rightQueryEntry) {
            currentSchema.push({
              name: rightTableName,
              columns: rightQueryEntry.fields || [],
            });
          } else if (!leftQueryEntry && leftTableName === rightTableName) {
          // Special case: if left and right are same, and left wasn't found, try to use the raw schema
            const matchingSchema = (schema || []).find(t => normalizeTblName(t.name) === normalizeTblName(rightTableName));
            if (matchingSchema) {
              currentSchema.push({
                name: matchingSchema.name,
                columns: matchingSchema.columns || [],
              });
            }
          }
        }
      }

      // If not in SQL mode, return null as per your requirement
      if (mode !== 'sql') return null;

      /* quick in-memory filter for table & column names */
      const filter = this.state.schemaFilter.trim().toLowerCase();
      const matches = s => (filter ? s.toLowerCase().includes(filter) : true);

      return (
        <div
          style={{
            width: this.state.schemaWidth,
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            borderRight: '1px solid #ddd',
            background: '#fafafa',
            flexShrink: 0,
          }}
        >
          {/* filter box */}
          <div style={{ padding: 6, flexShrink: 0 }}>
            <input
              type="text"
              className="form-control"
              placeholder="Search schema…"
              value={this.state.schemaFilter}
              onChange={this.handleSchemaFilter}
            />
          </div>

          {/* table / column list */}
          <div style={{ overflowY: 'auto', flexGrow: 1, padding: '0 6px 6px 6px' }}>
            {(currentSchema || []).filter(t => matches(t.name)).map((tbl) => {
              const isOpen = !!this.state.expandedTables[tbl.name];
              return (
                <div key={tbl.name} style={{ marginBottom: 6 }}>
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => this.toggleTable(tbl.name)}
                    style={{ display: 'flex', alignItems: 'center', cursor: 'pointer' }}
                  >
                    {isOpen ? <ExpandMoreIcon fontSize="small" /> : <ChevronRightIcon fontSize="small" />}
                    <span
                      onDoubleClick={() => this.insertAtCursor(tbl.name)}
                      style={{ marginLeft: 4, userSelect: 'none' }}
                    >
                      {tbl.name}
                    </span>
                  </div>
                  {isOpen && (
                  <ul style={{ listStyle: 'none', paddingLeft: 18 }}>
                    {(tbl.columns || [])
                      .filter((col) => {
                        const nm = typeof col === 'string' ? col : col.name;
                        return matches(nm);
                      })
                      .map((col) => {
                        const nm = typeof col === 'string' ? col : col.name;
                        return (
                        <li
                          key={nm}
                          style={{ cursor: 'pointer' }}
                          onClick={() => this.insertAtCursor(`${tbl.name}.${nm}`)}
                        >
                          {nm}
                        </li>
                        );
                      })}
                  </ul>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      );
    };


    const modKey = KeyboardShortcuts.modKey;

    const rqbFields = this.state.rqbAvailableFields.length
      ? this.state.rqbAvailableFields.map(f => ({ name: f, label: f }))
      : (schema || []).flatMap(t => (t.columns || []).map(c => ({
        name: `${t.name}.${c.name}`,
        label: `${t.name}.${c.name}`,
      })));

    const rootCls = mode === 'visual' ? 'visual-mode' : 'sql-mode';

    // Prepare DataGrid columns with custom headerClassName and no sorting
    const preparedLeftColumns = leftPreview.columns.map((col) => {
      const fullKey = `${leftTableName}.${col.field}`;
      return {
        ...col,
        sortable: false,
        headerClassName: selectedLeft.includes(fullKey) ? 'selected-header' : '',
      };
    });

    const preparedRightColumns = rightPreview.columns.map((col) => {
      const fullKey = `${rightTableName}.${col.field}`;
      return {
        ...col,
        sortable: false,
        headerClassName: selectedRight.includes(fullKey) ? 'selected-header' : '',
      };
    });

    return (
      <section
        className={`tsqe-root ${rootCls}`}
        style={{
          display: 'flex',
          flexDirection: 'column',
          height: '100%', // Fill parent container
        }}
      >
        {isNew && (
        <div style={{ padding: '8px 16px', background: '#fff', borderBottom: '1px solid #e5e5e5', flexShrink: 0 }}>
          <MuiTextField
            label="Query Name"
            value={this.state.name}
            onChange={e => this.setState({ name: e.target.value })}
            variant="outlined"
            size="small"
            fullWidth
            autoFocus
          />
        </div>
        )}

        {/* MAIN CONTENT AREA */}
        <div style={{ flex: '1 1 auto', position: 'relative', display: 'flex', flexDirection: 'row', minHeight: 0 }}>

          {renderSchemaBrowser()}
          {mode === 'sql' && (
          <div
            role="presentation"
            onMouseDown={this.startHResize}
            style={{
              width: '6px',
              cursor: 'ew-resize',
              background: '#c4c4c4',
              flexShrink: 0,
              zIndex: 3,
            }}
          />
          )}

          {/* SQL Editor and Visual Builder Container */}
          <div style={{ flex: '1 1 auto', display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden' }}>
            {/* SQL Editor Area */}
            <div
              ref={this.aceEditorContainerRef}
              style={{
                display: mode === 'sql' ? 'flex' : 'none',
                flexDirection: 'column',
                height: '100%',
              }}
            >
              <div style={{ flex: `0 0 ${this.state.sqlEditorHeight}px`, position: 'relative' }}>
                <AceEditor
                  ref={this.editorRef}
                  theme="textmate"
                  mode={dataSource.syntax || 'sql'}
                  value={queryText}
                  editorProps={{ $blockScrolling: Infinity }}
                  width="100%"
                  height="100%"
                  setOptions={{
                    behavioursEnabled: true,
                    enableSnippets: true,
                    enableBasicAutocompletion: true,
                    enableLiveAutocompletion: !liveAutocompleteDisabled && autocompleteQuery,
                    autoScrollEditorIntoView: true,
                    wrap: 'free',
                  }}
                  showPrintMargin={false}
                  wrapEnabled
                  onLoad={this.onAceLoad}
                  onChange={this.updateQuery}
                  onSelectionChange={this.updateSelected}
                />
              </div>
              <div
                role="presentation"
                style={{
                  height: '6px',
                  cursor: 'ns-resize',
                  background: '#c4c4c4',
                  userSelect: 'none',
                  flexShrink: 0,
                }}
                onMouseDown={this.startVResize}
              />
              <div style={{ flex: '1 1 auto', background: '#f0f0f0', padding: '8px' }}>
                {/* This is where query results would typically go in SQL mode */}
                <Typography>Query results will be displayed here.</Typography>
              </div>
            </div>


            {/* VISUAL BUILDER */}
            {mode === 'visual' && (
            <div
              className="visual-builder-overlay"
              style={{
                display: 'flex',
                flexDirection: 'column',
                height: '100%',
                overflow: 'auto', // This is the SINGLE scrolling container
              }}
            >
              {/* ─────────── TOP: TABLE LISTS / RELATION / RULES ─────────── */}
              <Box
                display="flex"
                flex="0 0 auto"
                p={1}
                style={{
                  borderBottom: '1px solid #ddd',
                }}
              >
                <Box display="flex" flexShrink={0}>
                  {/* Primary Table List */}
                  <Box width="240px" p={1} style={{ borderRight: '1px solid #ddd' }}>
                    <Box
                      display="flex"
                      justifyContent="space-between"
                      alignItems="center"
                    >
                      <Typography
                        variant="subtitle1"
                        style={{ fontWeight: 'bold', fontSize: '1.2rem' }}
                      >
                        Primary Table
                      </Typography>

                      {/* ★ NEW dynamic Join/Clear button */}
                      <button
                        type="button"
                        className="btn btn-default btn-sm"
                        onClick={
                                joinClause
                                  ? this.handleClearJoin
                                  : this.handleJoinClick
                              }
                      >
                        {joinClause ? 'Clear Join' : '+Join'}
                      </button>
                    </Box>
                    {queriesList
                      .filter(q => (q.tableName || q.name) !== rightTableName)
                      .map((q) => {
                        const name = q.tableName || q.name;
                        const isDataSource = q.data_source_id !== undefined;
                        const dataSourceId = q.data_source_id || q.id;
                        const dataSourceType = q.type;
                        const isExpanded = this.state.expandedDataSources[dataSourceId];
                        const schema = this.state.dataSourceSchemas[dataSourceId] || [];
                        const isExternal = dataSourceType === 'external';

                        return (
                          <div key={q.id || name} style={{ marginBottom: '4px' }}>
                            <div style={{ display: 'flex', alignItems: 'center' }}>
                              {/* Expand/Collapse button for non-external data sources */}
                              {isDataSource && !isExternal && (
                                <button
                                  type="button"
                                  onClick={() => this.toggleDataSourceExpansion(dataSourceId, dataSourceType)}
                                  style={{
                                    background: 'none',
                                    border: 'none',
                                    cursor: 'pointer',
                                    padding: '0 4px',
                                    fontSize: '12px',
                                  }}
                                >
                                  {isExpanded ? '▼' : '▶'}
                                </button>
                              )}
                              
                              {/* Data source name - external files are selectable, database sources show schema */}
                              {isDataSource && isExternal ? (
                                <MuiFormControlLabel
                                  control={(
                                    <MuiCheckbox
                                      checked={leftTableName === name}
                                      onChange={() => {
                                        // Set the data source ID before selecting the file
                                        this.setState({ selectedDataSourceId: dataSourceId }, () => {
                                          this.handlePrimaryTableChange(name);
                                        });
                                      }}
                                      color="primary"
                                    />
                                  )}
                                  label={
                                    <span>
                                      {name}
                                      <span style={{ fontSize: '0.75rem', color: '#999', marginLeft: '4px' }}>(file)</span>
                                    </span>
                                  }
                                />
                              ) : isDataSource ? (
                                <span style={{ 
                                  fontWeight: 'bold', 
                                  fontSize: '0.9rem',
                                  color: '#333',
                                }}>
                                  {name}
                                </span>
                              ) : (
                                <MuiFormControlLabel
                                  control={(
                                    <MuiCheckbox
                                      checked={leftTableName === name}
                                      onChange={() => this.handlePrimaryTableChange(name)}
                                      color="primary"
                                    />
                                  )}
                                  label={name}
                                />
                              )}
                            </div>

                            {/* Searchable dropdown for database tables only (not files) */}
                            {isDataSource && !isExternal && isExpanded && (
                              <div style={{ 
                                marginTop: '4px',
                                marginLeft: '8px',
                                border: '1px solid #ddd',
                                borderRadius: 4,
                                background: '#fff',
                                boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
                              }}>
                                {/* Search input */}
                                <div style={{ padding: '8px', borderBottom: '1px solid #eee' }}>
                                  <input
                                    type="text"
                                    placeholder="🔍 Search tables..."
                                    value={this.state.tableSearchTerms[dataSourceId] || ''}
                                    onChange={(e) => {
                                      e.stopPropagation();
                                      e.preventDefault();
                                      this.setState(prev => ({
                                        tableSearchTerms: {
                                          ...prev.tableSearchTerms,
                                          [dataSourceId]: e.target.value
                                        }
                                      }));
                                    }}
                                    onClick={(e) => e.stopPropagation()}
                                    onKeyDown={(e) => e.stopPropagation()}
                                    onFocus={(e) => e.stopPropagation()}
                                    style={{
                                      width: '100%',
                                      padding: '6px 8px',
                                      border: '1px solid #ddd',
                                      borderRadius: 4,
                                      fontSize: '0.9rem',
                                      boxSizing: 'border-box'
                                    }}
                                  />
                                </div>
                                
                                {/* Table list */}
                                <div style={{ 
                                  maxHeight: '300px', 
                                  overflowY: 'auto',
                                  padding: '4px'
                                }}>
                                  {schema.length === 0 ? (
                                    <div style={{ padding: '8px', fontSize: '0.85rem', color: '#999', fontStyle: 'italic', textAlign: 'center' }}>
                                      Loading tables...
                                    </div>
                                  ) : (() => {
                                    const searchTerm = this.state.tableSearchTerms[dataSourceId] || '';
                                    const filteredTables = schema.filter(table => 
                                      table.name.toLowerCase().includes(searchTerm.toLowerCase())
                                    );
                                    
                                    return filteredTables.length === 0 ? (
                                      <div style={{ padding: '8px', fontSize: '0.85rem', color: '#999', fontStyle: 'italic', textAlign: 'center' }}>
                                        No tables found
                                      </div>
                                    ) : (
                                      filteredTables.map((table) => {
                                        const tableName = table.name;
                                        return (
                                          <MuiFormControlLabel
                                            key={tableName}
                                            control={(
                                              <MuiCheckbox
                                                checked={leftTableName === tableName}
                                                onChange={(e) => {
                                                  e.stopPropagation();
                                                  this.setState({ 
                                                    selectedDataSourceId: dataSourceId,
                                                    expandedDataSources: {
                                                      ...this.state.expandedDataSources,
                                                      [dataSourceId]: false
                                                    }
                                                  }, () => {
                                                    this.handlePrimaryTableChange(tableName);
                                                  });
                                                }}
                                                color="primary"
                                                size="small"
                                              />
                                            )}
                                            label={tableName}
                                            style={{ 
                                              display: 'block',
                                              marginLeft: 0,
                                              marginRight: 0
                                            }}
                                          />
                                        );
                                      })
                                    );
                                  })()}
                                </div>
                                
                                {/* Footer with count */}
                                {schema.length > 0 && (() => {
                                  const searchTerm = this.state.tableSearchTerms[dataSourceId] || '';
                                  const filteredCount = schema.filter(table => 
                                    table.name.toLowerCase().includes(searchTerm.toLowerCase())
                                  ).length;
                                  
                                  return (
                                    <div style={{ 
                                      padding: '6px 8px', 
                                      borderTop: '1px solid #eee',
                                      fontSize: '0.75rem',
                                      color: '#999',
                                      textAlign: 'center'
                                    }}>
                                      {filteredCount} of {schema.length} tables
                                    </div>
                                  );
                                })()}
                              </div>
                            )}
                          </div>
                        );
                      })}
                  </Box>

                  {joinClicked && (
                  <>
                    {/* Secondary Table List */}
                    <Box
                      width="240px"
                      p={1}
                      style={{ borderRight: '1px solid #ddd' }}
                    >
                      <Typography
                        variant="subtitle1"
                        style={{ fontWeight: 'bold', fontSize: '1.2rem' }}
                      >
                        Secondary Table
                      </Typography>
                      {queriesList
                        .filter(q => (q.tableName || q.name) !== leftTableName)
                        .map((q) => {
                          const name = q.tableName || q.name;
                          const isDataSource = q.data_source_id !== undefined;
                          const dataSourceId = q.data_source_id || q.id;
                          const dataSourceType = q.type;
                          const isExpanded = this.state.expandedDataSources[dataSourceId];
                          const schema = this.state.dataSourceSchemas[dataSourceId] || [];
                          const isExternal = dataSourceType === 'external';

                          return (
                            <div key={q.id || name} style={{ marginBottom: '4px' }}>
                              <div style={{ display: 'flex', alignItems: 'center' }}>
                                {/* Expand/Collapse button for non-external data sources */}
                                {isDataSource && !isExternal && (
                                  <button
                                    type="button"
                                    onClick={() => this.toggleDataSourceExpansion(dataSourceId, dataSourceType)}
                                    style={{
                                      background: 'none',
                                      border: 'none',
                                      cursor: 'pointer',
                                      padding: '0 4px',
                                      fontSize: '12px',
                                    }}
                                  >
                                    {isExpanded ? '▼' : '▶'}
                                  </button>
                                )}
                                
                                {/* Data source name - external files are selectable, database sources show schema */}
                                {isDataSource && isExternal ? (
                                  <MuiFormControlLabel
                                    control={(
                                      <MuiCheckbox
                                        checked={rightTableName === name}
                                        onChange={() => {
                                          // Set the data source ID before selecting the file
                                          this.setState({ selectedDataSourceId: dataSourceId }, () => {
                                            this.handleRightTableSelect(name);
                                          });
                                        }}
                                        color="primary"
                                      />
                                    )}
                                    label={
                                      <span>
                                        {name}
                                        <span style={{ fontSize: '0.75rem', color: '#999', marginLeft: '4px' }}>(file)</span>
                                      </span>
                                    }
                                  />
                                ) : isDataSource ? (
                                  <span style={{ 
                                    fontWeight: 'bold', 
                                    fontSize: '0.9rem',
                                    color: '#333',
                                  }}>
                                    {name}
                                  </span>
                                ) : (
                                  <MuiFormControlLabel
                                    control={(
                                      <MuiCheckbox
                                        checked={rightTableName === name}
                                        onChange={() => this.handleRightTableSelect(name)}
                                        color="primary"
                                      />
                                    )}
                                    label={name}
                                  />
                                )}
                              </div>

                              {/* Searchable dropdown for database tables only (not files) */}
                              {isDataSource && !isExternal && isExpanded && (
                                <div style={{ 
                                  marginTop: '4px',
                                  marginLeft: '8px',
                                  border: '1px solid #ddd',
                                  borderRadius: 4,
                                  background: '#fff',
                                  boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
                                }}>
                                  {/* Search input */}
                                  <div style={{ padding: '8px', borderBottom: '1px solid #eee' }}>
                                    <input
                                      type="text"
                                      placeholder="🔍 Search tables..."
                                      value={this.state.tableSearchTerms[dataSourceId] || ''}
                                      onChange={(e) => {
                                        e.stopPropagation();
                                        e.preventDefault();
                                        this.setState(prev => ({
                                          tableSearchTerms: {
                                            ...prev.tableSearchTerms,
                                            [dataSourceId]: e.target.value
                                          }
                                        }));
                                      }}
                                      onClick={(e) => e.stopPropagation()}
                                      onKeyDown={(e) => e.stopPropagation()}
                                      onFocus={(e) => e.stopPropagation()}
                                      style={{
                                        width: '100%',
                                        padding: '6px 8px',
                                        border: '1px solid #ddd',
                                        borderRadius: 4,
                                        fontSize: '0.9rem',
                                        boxSizing: 'border-box'
                                      }}
                                    />
                                  </div>
                                  
                                  {/* Table list */}
                                  <div style={{ 
                                    maxHeight: '300px', 
                                    overflowY: 'auto',
                                    padding: '4px'
                                  }}>
                                    {schema.length === 0 ? (
                                      <div style={{ padding: '8px', fontSize: '0.85rem', color: '#999', fontStyle: 'italic', textAlign: 'center' }}>
                                        Loading tables...
                                      </div>
                                    ) : (() => {
                                      const searchTerm = this.state.tableSearchTerms[dataSourceId] || '';
                                      const filteredTables = schema.filter(table => 
                                        table.name.toLowerCase().includes(searchTerm.toLowerCase())
                                      );
                                      
                                      return filteredTables.length === 0 ? (
                                        <div style={{ padding: '8px', fontSize: '0.85rem', color: '#999', fontStyle: 'italic', textAlign: 'center' }}>
                                          No tables found
                                        </div>
                                      ) : (
                                        filteredTables.map((table) => {
                                          const tableName = table.name;
                                          return (
                                            <MuiFormControlLabel
                                              key={tableName}
                                              control={(
                                                <MuiCheckbox
                                                  checked={rightTableName === tableName}
                                                  onChange={(e) => {
                                                    e.stopPropagation();
                                                    this.setState({ 
                                                      selectedDataSourceId: dataSourceId,
                                                      expandedDataSources: {
                                                        ...this.state.expandedDataSources,
                                                        [dataSourceId]: false
                                                      }
                                                    }, () => {
                                                      this.handleRightTableSelect(tableName);
                                                    });
                                                  }}
                                                  color="primary"
                                                  size="small"
                                                />
                                              )}
                                              label={tableName}
                                              style={{ 
                                                display: 'block',
                                                marginLeft: 0,
                                                marginRight: 0
                                              }}
                                            />
                                          );
                                        })
                                      );
                                    })()}
                                  </div>
                                  
                                  {/* Footer with count */}
                                  {schema.length > 0 && (() => {
                                    const searchTerm = this.state.tableSearchTerms[dataSourceId] || '';
                                    const filteredCount = schema.filter(table => 
                                      table.name.toLowerCase().includes(searchTerm.toLowerCase())
                                    ).length;
                                    
                                    return (
                                      <div style={{ 
                                        padding: '6px 8px', 
                                        borderTop: '1px solid #eee',
                                        fontSize: '0.75rem',
                                        color: '#999',
                                        textAlign: 'center'
                                      }}>
                                        {filteredCount} of {schema.length} tables
                                      </div>
                                    );
                                  })()}
                                </div>
                              )}
                            </div>
                          );
                        })}
                    </Box>

                    {/* Relation Properties (hideQuerySelectors=true hides the left/right selectors inside) */}
                    <Box
                      width="340px"
                      p={1}
                      style={{ borderRight: '1px solid #ddd' }}
                    >
                      <JoinBuilder
                        leftTable={leftTableName || 'Project Queries'}
                        rightTable={rightTableName || 'Project Queries'}
                        leftFields={queriesList}
                        rightFields={queriesList}
                        hideQuerySelectors
                        onChange={this.handleJoinChange}
                        // ★ UPDATED: Pass parsed initial values to JoinBuilder
                        initialJoinType={initialJoinType}
                        initialJoinOperand={initialJoinOp}
                        initialLeftTableJoinColumn={initialLeftCol}
                        initialRightTableJoinColumn={initialRightCol}
                      />
                    </Box>
                  </>
                  )}

                  {/* Rules / Group Window */}
                  <Box minWidth="500px" p={1}>
                    <QueryBuilder
                      ref={(r) => {
                        this._queryBuilderRef = r;
                      }}
                      fields={rqbFields}
                      query={visualQuery}
                      onQueryChange={this.handleFilterChange}
                      controlElements={rqbControls}
                      controlClassnames={{ rule: 'rqb-rule-grid' }}
                      showAddGroupAction={false}
                      showAddRuleAction={false}
                      showCombinatorsBetweenRules
                    />
                    <Box
                      className="rqb-add-rule-below"
                      style={{ marginTop: '8px' }}
                    >
                      <button
                        type="button"
                        className="rqb-add-rule"
                        onClick={this.addRuleBelow}
                      >
                        + Add Filter
                      </button>
                    </Box>
                  </Box>
                </Box>
              </Box>

              {/* ─────────── MIDDLE: PREVIEWS ─────────── */}
              <Box p={2} flexShrink={0} key={`preview-area-${this.state.previewVersion}`}>
                {/* Primary Preview */}
                {leftTableName && (
                <Box mb={3}>
                  <Typography
                    variant="body1"
                    style={{
                      fontWeight: 'bold',
                      fontSize: '1.2rem',
                      marginBottom: '.5rem',
                    }}
                  >
                    Primary Table ({leftTableName})
                  </Typography>
                  <div style={{ width: '100%' }}>
                    <DataGrid
                      rows={leftPreview.rows}
                      columns={preparedLeftColumns}
                      pageSize={5}
                      rowsPerPageOptions={[5]}
                      hideFooterSelectedRowCount
                      disableColumnMenu
                      autoHeight
                      onColumnHeaderClick={(params) => {
                        this.togglePrimaryColumn(params.field);
                      }}
                    />
                  </div>
                </Box>
                )}

                {/* Secondary Preview */}
                {rightTableName && (
                <Box mb={3}>
                  <Typography
                    variant="body1"
                    style={{
                      fontWeight: 'bold',
                      fontSize: '1.2rem',
                      marginBottom: '.5rem',
                    }}
                  >
                    Secondary Table ({rightTableName})
                  </Typography>
                  <div style={{ width: '100%' }}>
                    <DataGrid
                      rows={rightPreview.rows}
                      columns={preparedRightColumns}
                      pageSize={5}
                      rowsPerPageOptions={[5]}
                      hideFooterSelectedRowCount
                      disableColumnMenu
                      autoHeight
                      onColumnHeaderClick={(params) => {
                        this.toggleSecondaryColumn(params.field);
                      }}
                    />
                  </div>
                </Box>
                )}
              </Box>

            </div>
            )}
          </div>
        </div>

        {/* FOOTER CONTROLS */}
        <div
          className="editor__control"
          style={{
            background: '#fff',
            borderTop: '1px solid #e5e5e5',
            padding: 8,
            flexShrink: 0,
            zIndex: 10,
          }}
        >
          <div className="form-inline d-flex align-items-center">

            {/* save */}
            {(canEdit || isNew) && (
            <Tooltip placement="top" title={isNew ? 'Save Query' : `${modKey}+S`}>
              <button
                type="button"
                className="btn btn-default m-l-5"
                onClick={isNew ? this.saveNewQuery : this.saveExistingQuery}
                disabled={isNew ? !(this.state.name && this.state.queryText) : !isDirty}
              >
                <span className="fa fa-floppy-o" />
                <span className="hidden-xs m-l-5">Save</span>
                {!isNew && isDirty ? '*' : null}
              </button>
            </Tooltip>
            )}

            <Tooltip placement="top" title="Toggle Editor Mode">
              <button
                type="button"
                className="btn btn-default m-l-5"
                onClick={this.toggleEditorMode}
              >
                <i className={`fa fa-${mode === 'visual' ? 'code' : 'table'}`} />
                <span className="hidden-xs m-l-5">
                  {mode === 'visual' ? 'SQL Editor' : 'Visual Editor'}
                </span>
              </button>
            </Tooltip>

            {/* add project */}
            <button
              type="button"
              className="btn btn-default m-l-5"
              onClick={this.openEditProjectsDialog}
            >
              <i className="zmdi zmdi-plus m-r-5" />
              Add&nbsp;Project
            </button>

            {/* execute */}
            <Tooltip placement="top" title="Execute Query">
              <button
                type="button"
                className={`btn btn-primary m-l-5${
                  queryExecuting || !canExecuteQuery ? ' disabled' : ''
                }`}
                disabled={queryExecuting || !canExecuteQuery}
                onClick={this.handleExecute}
              >
                <span className="zmdi zmdi-play" />
                <span className="hidden-xs m-l-5">Execute</span>
              </button>
            </Tooltip>

            {/* code editor */}
            <button
              type="button"
              className="btn btn-default m-l-5"
              onClick={() => document.dispatchEvent(
                new CustomEvent('openCodeEditor', { detail: { queryId } }),
              )
              }
            >
              <i className="fa fa-code" />
              <span className="hidden-xs m-l-5">&lt;/&gt; Code Editor</span>
            </button>

            {/* new parameter */}
            <Tooltip
              placement="top"
              title={(
                <span>
                  Add New Parameter (<i>{modKey}+P</i>)
                </span>
              )}
            >
              <button
                type="button"
                className="btn btn-default m-l-5"
                onClick={addNewParameter}
              >
                {'{{ }}'}
              </button>
            </Tooltip>

            {/* format */}
            <Tooltip
              placement="top"
              title={(
                <span>
                  Format Query (<i>{modKey}+Shift+F</i>)
                </span>
              )}
            >
              <button
                type="button"
                className="btn btn-default m-l-5"
                onClick={this.formatQuery}
              >
                <span className="zmdi zmdi-format-indent-increase" />
              </button>
            </Tooltip>

            {/* autocomplete */}
            <AutocompleteToggle
              state={autocompleteQuery}
              onToggle={this.toggleAutocomplete}
              disabled={this.state.liveAutocompleteDisabled}
            />

            {/* datasource select */}
            <select
              className="form-control datasource-small flex-fill w-100 m-l-5"
              onChange={e => this.props.updateDataSource(Number(e.target.value))}
              disabled={!this.props.isQueryOwner}
              value={this.props.dataSource.id || ''}
            >
              {visibleDs.map(ds => (
                <option key={ds.id} value={ds.id}>
                  {ds.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </section>
    );
  }
}


export const TSQueryEditorReact = TSQueryEditor;
export default function init(ngModule) {
  ngModule.component(
    'tsQueryEditor',
    react2angular(TSQueryEditor, [
      'queryId',
      'queryText',
      'schema',
      'addNewParameter',
      'dataSources',
      'dataSource',
      'canEdit',
      'isNew',
      'isDirty',
      'isQueryOwner',
      'updateDataSource',
      'canExecuteQuery',
      'executeQuery',
      'queryExecuting',
      'saveQuery',
      'updateQuery',
      'updateSelectedQuery',
      'listenForResize',
      'listenForEditorCommand',
      'projectIds',
    ]),
  );

  ngModule.controller('TSQueryViewCtrl', QueryViewCtrl);

  return {
    '/tsqueries/new': {
      template: tsqueryTemplate,
      layout: 'fixed',
      controller: 'TSQueryViewCtrl',
      reloadOnSearch: false,
      resolve: {
        query: () => {
          'ngInject';

          console.log('[TSQueryEditor.jsx] Creating NEW query via route /tsqueries/new');
          return new Query({
            name: 'New Query',
            query: '',
            description: '',
            is_draft: true,
            tags: [],
            user: {
              id: currentUser.id,
              name: currentUser.name,
            },
          });
        },
        dataSources: DataSource => DataSource.query().$promise,
      },
    },
  };
}

init.init = true;
