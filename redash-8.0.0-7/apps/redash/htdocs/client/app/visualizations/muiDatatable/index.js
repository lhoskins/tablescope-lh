// Change Timestamp: 2025-07-12 18:30:00


import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import { DragDropContext,
  Droppable,
  Draggable } from 'react-beautiful-dnd'; import { registerVisualization } from '@/visualizations'; import { DataGrid,
  GridColumnMenuContainer,
  SortGridMenuItems,
  GridFilterMenuItem,
  HideGridColMenuItem,
  GridColumnsMenuItem } from '@material-ui/data-grid'; import { FormControl,
  InputLabel,
  Select,
  MenuItem,
  Typography,
  Box,
  ListItemIcon,
  ListItemText,
  Paper,
  Button } from '@material-ui/core';
import FilterListIcon from '@material-ui/icons/FilterList';
import ArrowBackIcon from '@material-ui/icons/ArrowBack';
import createscopeicon from './assets/createscopeicon.png';
import editscopeicon from './assets/editscopeicon.png';
import CreateScope from './CreateScope';
import EditScope from './EditScope'; // This should be EditScope, fixing a potential typo
/* ────────────────── column layout API helpers ────────────────── */
// Helper: derive org slug from URL → /<org>/something
const getOrgSlug = () => window.location.pathname.split('/')[1] || 'default';

async function fetchColumnLayout(queryId) {
  try {
    const orgSlug = getOrgSlug();
    const resp = await fetch(`/${orgSlug}/api/column_layouts?query_id=${queryId}`, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
    if (!resp.ok) throw new Error('fetchColumnLayout failed');
    const payload = await resp.json();
    return payload.columns || [];
  } catch (err) {
    console.error('[MUI-DG] fetchColumnLayout error →', err);
    return [];
  }
}

async function saveLayout(queryId, cols) {
  try {
    const orgSlug = getOrgSlug();
    const payload = {
      query_id: queryId,
      columns: cols.map((c, idx) => ({
        field: c.field,
        hide: c.hide || c.hide === true ? c.hide : false,
        order: idx,
      })),
    };
    await fetch(`/${orgSlug}/api/column_layouts`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    console.error('[MUI-DG] saveLayout error →', err);
  }
}

// ────────────────────────────────────────────────────────────
// Utility to normalize quoted identifiers before compare
const stripQuotes = s => (typeof s === 'string'
  ? s.replace(/^["'`]+|["'`]+$/g, '')
  : s);

/* ──────────────────────────────────────────────────────────────
   DEBUG – force-print what the page knows about the current
   query / query-id / SQL text / table names.
   ────────────────────────────────────────────────────────────── */
(() => {
  console.group('[QUERY-ID DEBUG]');

  /** 1️ URL-derived id (…/query/123 or …/queries/123) */
  const urlMatch = window.location.pathname.match(/\/(?:query|queries)\/(\d+)/);
  console.log('URL regex →', urlMatch ? urlMatch[1] : '(none)');

  /** 2️ Angular page globals Redash puts on window */

  /** 3️ Last value we stored in helpers (if any) */
  console.log('window.__queryId        →', window.__queryId);
  console.log('window.__currentSourceTable    →', window.__currentSourceTable);

  /** 4️ Try to extract the first table name from SQL (if query text exists) */
  const sqlText =
    (window.query && window.query.query_text) ||
    (window.queryResult && window.queryResult.query && window.queryResult.query.query_text) ||
    '';
  const m = /\bfrom\s+[`"'[\]]*([A-Za-z0-9_.]+)[`"'[\]]*/i.exec(sqlText);
  console.log('Table parsed from SQL          →', m ? m[1] : '(none)');

  console.groupEnd();

  /* ───────────── Alert once with Query ID & Name (from ProjectDetailPage) ───────────── */


  document.addEventListener('query-selected', async (e) => {
    if (!e || !e.detail) return;
    const { queryId, queryName } = e.detail;

    // Helper to show alert & update global
    const show = (nm) => {
      if (nm) {
        window.__currentSourceTable = nm;
      }
      // Removed alert() as per instructions
      // alert(`Current Query ID: ${queryId}\nQuery Name: ${nm || '(none)'}`);
    };

    if (queryName) {
      show(queryName);
      return;
    }

    // Fallback 1: existing global set elsewhere
    if (window.__currentSourceTable) {
      show(window.__currentSourceTable);
      return;
    }

    // Fallback 2: fetch name via API
    if (queryId) {
      try {
        const orgSlug = getOrgSlug();
        const res = await fetch(`/${orgSlug}/api/queries/${queryId}`, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
        if (res.ok) {
          const payload = await res.json();
          const nm = payload.name || payload.query || '';
          show(nm);
          return;
        }
      } catch (err) {
        console.error('[query-selected listener] fetch name failed →', err);
      }
    }

    // Final fallback
    show('(none)');
  }, { once: true });
})();

const DEFAULT_OPTIONS = { rowsPerPage: 10, filterType: 'dropdown' };

/* ─────────────────────────────────────  OPTIONS EDITOR  ─────────────────────────────────── */
export const MuiDatatableEditor = ({ options, onOptionsChange }) => {
  const handleChange = key => event => onOptionsChange({ ...options, [key]: event.target.value });

  return (
    <Box display="flex" flexDirection="column" p={2}>
      <Typography variant="subtitle1" gutterBottom>
        Table Settings
      </Typography>

      <FormControl variant="outlined" margin="dense">
        <InputLabel id="rows-per-page-label">Rows per page</InputLabel>
        <Select
          labelId="rows-per-page-label"
          value={options.rowsPerPage}
          onChange={handleChange('rowsPerPage')}
          label="Rows per page"
        >
          {[5, 10, 25, 50, 100].map(n => (
            <MenuItem key={n} value={n}>
              {n}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      <FormControl variant="outlined" margin="dense">
        <InputLabel id="filter-type-label">
          <FilterListIcon fontSize="small" style={{ marginRight: 4 }} />
          Filter style
        </InputLabel>
        <Select
          labelId="filter-type-label"
          value={options.filterType}
          onChange={handleChange('filterType')}
          label="Filter style"
        >
          <MenuItem value="dropdown">Dropdown</MenuItem>
          <MenuItem value="checkbox">Checkbox</MenuItem>
          <MenuItem value="textField">Text input</MenuItem>
        </Select>
      </FormControl>
    </Box>
  );
};

MuiDatatableEditor.propTypes = {
  options: PropTypes.shape({
    rowsPerPage: PropTypes.number,
    filterType: PropTypes.string,
  }).isRequired,
  onOptionsChange: PropTypes.func.isRequired,
};

/* ─────────────────────────────────────  COLUMN MENU  ───────────────────────────────────── */
const CustomColumnMenu = React.forwardRef((props, ref) => {
  const {
    hideMenu,
    currentColumn,
    onCreateScope,
    onEditScope,
    scopesList = [],
    sourceTable = '',
    queryId = '',
  } = props;

  const existingScope = scopesList.find(
    s => String(s.query_id) === String(queryId) && stripQuotes(s.source_field) === stripQuotes(currentColumn.field),
  );

  console.log(
    '[CustomColumnMenu] for column',
    currentColumn.field,
    'sourceTable',
    sourceTable,
    'existingScope →',
    existingScope,
  );

  const handleCreateScopeClick = (evt) => {
    if (onCreateScope) onCreateScope(currentColumn.field);
    hideMenu(evt);
  };

  const handleEditScopeClick = (evt) => {
    if (onEditScope) onEditScope(currentColumn.field);
    hideMenu(evt);
  };

  return (
    <GridColumnMenuContainer ref={ref} {...props}>
      <SortGridMenuItems column={currentColumn} onClick={hideMenu} />
      <GridFilterMenuItem column={currentColumn} onClick={hideMenu} />
      <HideGridColMenuItem column={currentColumn} onClick={hideMenu} />

      {existingScope ? (
        <MenuItem onClick={handleEditScopeClick}>
          <ListItemIcon>
            <img
              src={editscopeicon}
              alt="Edit Scope"
              style={{ width: 16, height: 16, display: 'block' }}
            />
          </ListItemIcon>
          <ListItemText primary="Edit Scope" />
        </MenuItem>
      ) : (
        <MenuItem onClick={handleCreateScopeClick}>
          <ListItemIcon>
            <img
              src={createscopeicon}
              alt="Create Scope"
              style={{ width: 16, height: 16, display: 'block' }}
            />
          </ListItemIcon>
          <ListItemText primary="Create Scope" />
        </MenuItem>
      )}

      <GridColumnsMenuItem column={currentColumn} onClick={hideMenu} />
    </GridColumnMenuContainer>
  );
});

CustomColumnMenu.propTypes = {
  hideMenu: PropTypes.func.isRequired,
  currentColumn: PropTypes.shape({ field: PropTypes.string.isRequired }).isRequired,
  onCreateScope: PropTypes.func,
  onEditScope: PropTypes.func,
  scopesList: PropTypes.array,
  sourceTable: PropTypes.string,
  queryId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
};
CustomColumnMenu.defaultProps = {
  onCreateScope: null,
  onEditScope: null,
  scopesList: [],
  sourceTable: '',
  queryId: '',
};

/* ─────────────────────────────────────  RENDERER  ─────────────────────────────────────── */

/* ───────────────────────  COLUMN REORDER BAR (DIY)  ─────────────────────── */
const ColumnReorderBar = ({ columns, onReorder }) => {
  const handleDragEnd = (result) => {
    if (!result.destination) return;
    const reordered = Array.from(columns);
    const [removed] = reordered.splice(result.source.index, 1);
    reordered.splice(result.destination.index, 0, removed);
    onReorder(reordered);
  };

  return (
    <DragDropContext onDragEnd={handleDragEnd}>
      <Droppable droppableId="columns-droppable" direction="horizontal">
        {provided => (
          <div
            ref={provided.innerRef}
            {...provided.droppableProps}
            style={{ display: 'flex', flexWrap: 'wrap', marginBottom: 8 }}
          >
            {columns.map((col, idx) => (
              <Draggable key={col.field} draggableId={col.field} index={idx}>
                {dragProvided => (
                  <div
                    ref={dragProvided.innerRef}
                    {...dragProvided.draggableProps}
                    {...dragProvided.dragHandleProps}
                    style={{
                      userSelect: 'none',
                      padding: '4px 8px',
                      margin: '0 4px 4px 0',
                      border: '1px solid #ccc',
                      borderRadius: 4,
                      background: '#fafafa',
                      fontSize: 12,
                      ...dragProvided.draggableProps.style,
                    }}
                  >
                    {col.headerName}
                  </div>
                )}
              </Draggable>
            ))}
            {provided.placeholder}
          </div>
        )}
      </Droppable>
    </DragDropContext>
  );
};


export const MuiDatatableRenderer = ({ data, options }) => {
  const [sourceTable, setSourceTable] = useState(
    window.__currentSourceTable || '',
  );
  const [tablesMap, setTablesMap] = useState({});
  const [queriesList, setQueriesList] = useState([]);
  const [queriesByName, setQueriesByName] = useState({});

  /* ── sync queryId whenever sourceTable→queriesByName resolves ── */
  useEffect(() => {
    if (sourceTable && queriesByName[sourceTable]) {
      const newId = String(queriesByName[sourceTable]);
      if (newId && newId !== String(queryId)) {
        console.log('[MUI-DG] sync queryId from sourceTable →', newId);
        setQueryId(newId);
        window.__queryId = newId;
        window.__currentQueryId = newId;
      }
    }
  }, [sourceTable, queriesByName, queryId]);

  const [isCreateScopeOpen, setIsCreateScopeOpen] = useState(false);
  const [selectedColumn, setSelectedColumn] = useState(null);

  const [isEditScopeOpen, setIsEditScopeOpen] = useState(false);
  const [selectedScope, setSelectedScope] = useState(null);

  const [scopesList, setScopesList] = useState([]);
  const [columnOrder, setColumnOrder] = useState([]);
  
  // State for page size (rows per page)
  const [pageSize, setPageSize] = useState(options.rowsPerPage || 10);

  // NEW: State to hold data from the visual builder
  const [visualBuilderData, setVisualBuilderData] = useState(null);

  /* ─── fetch saved column layout on queryId change ─── */
  useEffect(() => {
    if (!queryId) return;
    fetchColumnLayout(queryId).then((cols) => {
      if (cols && cols.length) {
        // map to DataGrid column objects: find matching gridColumns
        const mapped = cols.map(({ field, hide }) => ({
          ...gridColumns.find(c => c.field === field) || { field, headerName: field },
          hide,
        }));
        setColumnOrder(mapped);
      }
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryId]);
  const [scopedData, setScopedData] = useState(null);
  // URL & org helpers
  const pathParts = window.location.pathname.split('/').filter(Boolean);
  const idxId = pathParts.findIndex(p => /^\d+$/.test(p));
  let orgPrefix = '';
  if (idxId > 0) orgPrefix = `/${pathParts.slice(0, idxId).join('/')}`;
  else if (pathParts.length) orgPrefix = `/${pathParts[0]}`;

  // ───────── detect & seed queryId ─────────
  const detectQueryId = () => {
    if (idxId !== -1) {
      return pathParts[idxId];
    }
    if (window.query && window.query.id) {
      return String(window.query.id);
    }
    if (
      window.queryResult &&
      window.queryResult.query &&
      window.queryResult.query.id
    ) {
      return String(window.queryResult.query.id);
    }
    const m = window.location.pathname.match(
      /(?:^|\/)(?:query|queries)\/(\d+)/,
    );
    return m ? m[1] : null;
  };

  // Combine URL / prior global
  const initialQueryId =
    detectQueryId() ||
    window.__queryId ||
    null;

  const [queryId, setQueryId] = useState(initialQueryId);
  /* ── bootstrap queryId + sourceTable when still null ── */
  useEffect(() => {
    if (!queryId && queriesList.length) {
    // pick current selected table's id if possible
      let chosen = queriesList.find(q => q.name === sourceTable);
      if (!chosen) {
        const sorted = [...queriesList]
          .filter(q => !q.is_archived)
          .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
        chosen = sorted[0] || queriesList[0];
      }
      if (chosen) {
        console.log('[MUI-DG] bootstrap queryId →', chosen.id, chosen.name);
        setQueryId(String(chosen.id));
        window.__queryId = String(chosen.id);
        window.__currentQueryId = String(chosen.id);
        if (!sourceTable) {
          setSourceTable(chosen.name);
          window.__currentSourceTable = chosen.name;
        }
      }
    }
  }, [queriesList, queryId, sourceTable]);

  // Mirror into the global for any other code that reads it
  if (queryId && window.__queryId !== queryId) {
    window.__queryId = queryId;
    window.__currentQueryId = queryId;
    console.log('[MUI-DG] initial queryId seeded →', queryId);
  }

  // ─── If still no queryId, seed from the first existing scope on load ───
  useEffect(() => {
    if (!queryId && scopesList.length) {
      const fallback = String(scopesList[0].query_id);
      console.log('[MUI-DG] seeding queryId from first scope →', fallback);
      setQueryId(fallback);
      window.__queryId = fallback;
      window.__currentQueryId = fallback;
    }
  }, [scopesList, queryId]);

  /* -- refresh scopes whenever queryId changes (continuous drill‑down) -- */
  useEffect(() => {
    if (!queryId) return;
    const scopesUrl = `${orgPrefix}/api/scopes?query_id=${queryId}`;
    console.log('[MUI-DG] refresh scopes →', scopesUrl);
    fetch(scopesUrl, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(r => r.json())
      .then(setScopesList)
      .catch(err => console.error('[MUI-DG] refresh scopes error →', err));
  }, [queryId]);

  /* -- when queryId changes, pull its definition & updated table/field map -- */
  useEffect(() => {
    if (!queryId) return;
    (async () => {
      try {
        await fetchQueryAndMaybeTables();
      } catch (err) {
        console.error('[MUI-DG] fetchQueryAndMaybeTables (queryId change) error →', err);
      }
    })();
  }, [queryId]);

  /* ---------- helper: fetch queries_with_field ---------- */
  const fetchQueriesWithField = async (pid) => {
    const url = `${orgPrefix}/api/projects/${pid}/queries_with_field`;
    console.log('[MUI-DG] GET queries_with_field →', url);
    const res = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const list = await res.json();
    console.log('[MUI-DG] queriesList loaded →', list);
    setQueriesList(list);
    console.log('DEBUG: Fetched queriesList:', list);

    // after we have list, auto-set sourceTable if queryId present
    if (queryId) {
      const hit = list.find(q => String(q.id) === String(queryId));
      if (hit && hit.name && hit.name !== sourceTable) {
        console.log('[MUI-DG] auto-setting sourceTable from queriesList →', hit.name);
        setSourceTable(hit.name);
        window.__currentSourceTable = hit.name;
      }
    }
    const map = {};
    const qid = {};
    list.forEach((q) => {
      map[q.name] = q.fields || [];
      qid[q.name] = q.id;
    });
    setTablesMap(map);
    setQueriesByName(qid);
  };

  /* ---------- helper: fetch query JSON ---------- */
  const fetchQueryAndMaybeTables = async () => {
    const url = `${orgPrefix}/api/queries/${queryId}`;
    console.log('[MUI-DG] GET query →', url);
    const res = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const q = await res.json();
    console.log('[MUI-DG] /api/queries response →', q);

    if (!sourceTable && q.query) {
      const m = /\bfrom\s+[`"'[\]]*([A-Za-z0-9_.]+)[`"'[\]]*/i.exec(q.query);
      if (m) {
        console.log('[MUI-DG] auto-setting sourceTable from SQL parse →', m[1]);
        setSourceTable(m[1]);
        window.__currentSourceTable = m[1];
      }
    }

    if (Array.isArray(q.project_id) && q.project_id.length) {
      const current = window.__currentProjectId;
      let pid = null;
      if (current && q.project_id.includes(Number(current))) pid = Number(current);
      if (!pid) pid = q.project_id.find(id => id != null) || q.project_id[0];
      window.__currentProjectId = pid;
      await fetchQueriesWithField(pid);
    }
  };

  /* ─────────── initial bootstrap ─────────── */
  useEffect(() => {
    // 1) fetch scopes
    const scopesUrl = `${orgPrefix}/api/scopes${queryId ? `?query_id=${queryId}` : ''}`;
    console.log('[MUI-DG] GET scopes →', scopesUrl);
    fetch(scopesUrl, { credentials: 'same-origin' })
      .then(r => r.json())
      .then((list) => {
        console.log('[MUI-DG] scopesList loaded →', list);
        setScopesList(list);
      })
      .catch(err => console.error('[MUI-DG] fetch scopes error →', err));

    // 2) fetch tables & queries
    (async () => {
      try {
        if (queryId) {
          await fetchQueryAndMaybeTables();
          return;
        }
        if (window.__currentProjectId) {
          await fetchQueriesWithField(window.__currentProjectId);
        }
      } catch (err) {
        console.error('[MUI-DG] init error →', err);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ── broadcast: query-selected ── */
  useEffect(() => {
    const onQuery = (e) => {
      console.log('[MUI-DG] broadcast query-selected →', e.detail);
      if (!e.detail) return;
      if (e.detail.queryId) {
        setQueryId(String(e.detail.queryId));
        window.__queryId = String(e.detail.queryId);
        window.__currentQueryId = String(e.detail.queryId);
      }
      if (e.detail.queryName) {
        setSourceTable(e.detail.queryName);
        window.__currentSourceTable = e.detail.queryName;
      }
    };
    document.addEventListener('query-selected', onQuery);
    return () => document.removeEventListener('query-selected', onQuery);
  }, []);

  /* ── broadcast: project-selected / source-table-detected ── */
  useEffect(() => {
    const handler = (e) => {
      console.log('[MUI-DG] broadcast event →', e.type, e.detail);
      if (e.type === 'project-selected' && e.detail && e.detail.projectId) {
        fetchQueriesWithField(e.detail.projectId);
      }
      if (e.detail && e.detail.tableName) {
        setSourceTable(e.detail.tableName);
        window.__currentSourceTable = e.detail.tableName;
      }
    };
    document.addEventListener('project-selected', handler);
    document.addEventListener('source-table-detected', handler);
    return () => {
      document.removeEventListener('project-selected', handler);
      document.removeEventListener('source-table-detected', handler);
    };
  }, []);

  /* ── listen for “scope-created” ── */
  useEffect(() => {
    const handler = (e) => {
      console.log('[MUI-DG] scope-created event →', e.detail);
      setScopedData({ columns: e.detail.columns, rows: e.detail.rows });
      setVisualBuilderData(null); // Clear visual builder data when a scope is applied
    };
    document.addEventListener('scope-created', handler);
    return () => document.removeEventListener('scope-created', handler);
  }, []);

  // NEW: Listen for 'visual-data-change' event from TSQueryEditor
  useEffect(() => {
    const handleVisualDataChange = (e) => {
      console.log('[MUI-DG] Visual data changed event received:', e.detail);
      setVisualBuilderData(e.detail); // Update state with new data from visual builder
      setScopedData(null); // Clear scopedData if visual builder is now controlling
    };
    document.addEventListener('visual-data-change', handleVisualDataChange);
    return () => document.removeEventListener('visual-data-change', handleVisualDataChange);
  }, []);

  /* seed sourceTable from current query */
  useEffect(() => {
    console.log('[MUI-DG] auto-seed effect →', { queryId, queriesList, sourceTable });
    if (queryId && queriesList.length && !sourceTable) {
      const current = queriesList.find(q => String(q.id) === String(queryId));
      if (current && current.name) {
        console.log('[MUI-DG] auto-setting sourceTable from current query →', current.name);
        setSourceTable(current.name);
        window.__currentSourceTable = current.name;
      }
    }
  }, [queriesList, queryId, sourceTable]);


  /* ─── open CreateScope ─── */
  const handleOpenCreateScope = (columnName) => {
    console.log('[MUI-DG] handleOpenCreateScope →', { columnName, sourceTable, scopesList });
    if (!sourceTable) {
      const hit = queriesList.find(q => String(q.id) == String(queryId));
      if (hit && hit.name) {
        setSourceTable(hit.name);
        window.__currentSourceTable = hit.name;
      }
    }
    setSelectedColumn(columnName);
    window.__pendingQueryId = queryId ? Number(queryId) : null;
    setIsCreateScopeOpen(true);
  };

  /* ─── after a new scope is successfully created ─── */
  const handleScopeCreated = (scopeObj) => {
    console.log('[MUI-DG] handleScopeCreated →', scopeObj);
    if (!scopeObj) {
      setIsCreateScopeOpen(false);
      return;
    }
    setScopesList((prev) => {
      if (scopeObj.id && prev.some(s => s.id === scopeObj.id)) return prev;
      return [...prev, scopeObj];
    });
    if (scopeObj.columns && scopeObj.rows) {
      setScopedData({ columns: scopeObj.columns, rows: scopeObj.rows });
      setVisualBuilderData(null); // Clear visual builder data when a scope is applied
    }
    setIsCreateScopeOpen(false);
  };

  const handleCloseCreateScope = () => {
    console.log('[MUI-DG] handleCloseCreateScope');
    setIsCreateScopeOpen(false);
  };


  /* ─── open EditScope ─── */
  const handleOpenEditScope = (columnName) => {
    const match = scopesList.find(
      s => String(s.query_id) === String(queryId) && stripQuotes(s.source_field) === columnName,
    );
    console.log('[MUI-DG] handleOpenEditScope → found match', match);
    if (!match) return;
    setSelectedScope(match);
    setIsEditScopeOpen(true);
  };
  const handleCloseEditScope = () => {
    console.log('[MUI-DG] handleCloseEditScope');
    setIsEditScopeOpen(false);
    setSelectedScope(null);
  };

  /* ─── apply EditScope locally ─── */

  /* ─── delete Scope locally ─── */
  const handleDeleteScope = (scopeId) => {
    console.log('[MUI-DG] handleDeleteScope →', scopeId);
    setScopesList(prev => prev.filter(s => s.id !== scopeId));
    setIsEditScopeOpen(false);
    setSelectedScope(null);
  };
  const handleSaveEdit = (updatedScope) => {
    console.log('[MUI-DG] handleSaveEdit →', updatedScope);
    setScopesList(prev => prev.map(s => (s.id === updatedScope.id ? updatedScope : s)));
  };


  const handleBarReorder = (cols) => {
    const normalized = cols.map(c => ({
      ...c,
      flex: c.flex || 1,
      minWidth: c.minWidth || 150,
    }));
    setColumnOrder(normalized);
    if (queryId) saveLayout(queryId, normalized);
  };

  /* ---- SCOPE FILTER cell click ---- */
  const handleCellClick = async (params) => {
    console.log('[MUI-DG | handleCellClick] Cell clicked. Params:', params);
    const colName = params.field;
    const value = params.value;

    // find scope that matches this column & current query
    const scope = scopesList.find(
      s => String(s.query_id) === String(queryId) &&
      stripQuotes(s.source_field) === stripQuotes(colName),
    );
    console.log('[MUI-DG | handleCellClick] Found scope:', scope);

    if (!scope) {
      console.log('[MUI-DG | handleCellClick] No scope found for this column. Aborting.');
      return; // no scope → no filter
    }

    const targetTable = scope.target_table;
    const targetField = scope.target_field;
    // Use explicit target_query_id from scope
    const targetQueryId = scope.target_query_id;
    console.log('[MUI-DG | handleCellClick] Target Query ID from scope:', targetQueryId);

    if (!targetQueryId) {
      console.warn('[SCOPE] missing queryId for target table', targetTable);
      return;
    }

    const url = `${orgPrefix}/api/scopes/filter` +
    `?project_id=${window.__currentProjectId}` +
    `&query_id=${targetQueryId}` +
    `&target_field=${encodeURIComponent(targetField)}` +
    `&value=${encodeURIComponent(value)}`;
    try {
      const res = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
      const resClone = res.clone();
      if (!res.ok) {
        console.error('[SCOPE] HTTP', res.status, url);
        return;
      }
      let payload;
      try {
        payload = await res.json();
      } catch (jsonErr) {
        const text = await resClone.text();
        console.error('[SCOPE] parsing JSON failed →', jsonErr, 'Response text:', text);
        return;
      }
      if (!payload.columns || !payload.rows) {
        console.error('[SCOPE] Unexpected response', payload);
        return;
      }

      console.log('[MUI-DG | handleCellClick] Firing drilldown. Checking queriesList...', queriesList);
      const targetQuery = queriesList.find(q => String(q.id) === String(targetQueryId));

      if (targetQuery) {
        try {
          // --- Show Scope Container and Update Details ---
          const scopeContainer = document.getElementById('scope-container');
          if (scopeContainer) {
            scopeContainer.style.display = 'inline-block';
          }

          let el;

          el = document.getElementById('scope-from-table');
          if (el) el.textContent = sourceTable || '-';

          el = document.getElementById('scope-to-table');
          if (el) el.textContent = targetTable || '-';

          el = document.getElementById('scope-from-field');
          if (el) el.textContent = colName || '-';

          el = document.getElementById('scope-to-field');
          if (el) el.textContent = targetField || '-';

          el = document.getElementById('scope-value');
          const _val = (value !== undefined && value !== null) ? value : '-';
          if (el) el.textContent = _val;
        } catch (e) {
          console.error('[MUI-DG] DOM label update error', e);
        }
      }

      console.log('[MUI-DG | handleCellClick] Found target query from queriesList:', targetQuery);
      if (targetQuery && targetQuery.name) {
        const detail = { queryName: targetQuery.name, queryId: targetQuery.id };
        console.log('[MUI-DG | handleCellClick] AGGRESSIVE FIX: Setting global variable `__drilldownQueryName` to:', detail.queryName);
        window.__drilldownQueryName = detail.queryName;

        // -------  Directly update Angular header (fallback) -------
        try {
          const wrapper = document.querySelector('.query-page-wrapper');
          if (wrapper && window.angular && window.angular.element) {
            const $ngEl = window.angular.element(wrapper);
            const $scope = $ngEl.scope() || $ngEl.isolateScope();
            if ($scope) {
              $scope.$applyAsync(() => {
                if ($scope.query) {
                  $scope.query.name = detail.queryName;
                }
              });
            }
          }
        } catch (err) {
          console.error('[MUI-DG] Angular header update failed →', err);
        }
      } else {
        console.warn('[MUI-DG | handleCellClick] Could not find target query in queriesList. Header will not update.');
      }


      /* -------- CONTINUOUS DRILL‑DOWN: update query context -------- */
      const isDrilldown = targetQuery && String(targetQueryId) !== String(queryId);
      if (isDrilldown) {
        /* update React state */
        setQueryId(String(targetQueryId));
        setSourceTable(targetQuery.name || targetTable);
        /* update globals for other scripts */
        window.__queryId = String(targetQueryId);
        window.__currentQueryId = String(targetQueryId);
        window.__currentSourceTable = targetQuery.name || targetTable;
        /* let listeners know */
        document.dispatchEvent(new CustomEvent('query-selected', { detail: { queryId: targetQueryId, queryName: targetQuery.name } }));
      }

      setScopedData({ columns: payload.columns, rows: payload.rows });
      setVisualBuilderData(null); // Clear visual builder data when a scope is applied

      if (targetQuery) {
        /* update React state */
        setQueryId(String(targetQueryId));
        setSourceTable(targetQuery.name || targetTable);
        /* update globals for other scripts */
        window.__queryId = String(targetQueryId);
        window.__currentQueryId = String(targetQueryId);
        window.__currentSourceTable = targetQuery.name || targetTable;
        /* let listeners know */
        document.dispatchEvent(new CustomEvent('query-selected', { detail: { queryId: targetQueryId, queryName: targetQuery.name } }));
      }

      setScopedData({ columns: payload.columns, rows: payload.rows });
      setVisualBuilderData(null); // Clear visual builder data when a scope is applied
    } catch (err) {
      console.error('[SCOPE] error', err);
    }
  };


  /* ─── render grid ─── */
  // Determine the primary data source: scopedData (drill-down) > visualBuilderData > original data
  const baseColumns = scopedData
    ? scopedData.columns
    : (visualBuilderData ? visualBuilderData.columns : data.columns);

  const baseRows = scopedData
    ? scopedData.rows
    : (visualBuilderData ? visualBuilderData.rows : data.rows);


  /* -- Base columns built from data -- */
  const gridColumns = baseColumns.map(col => ({
    field: col.name || col.field || col,
    headerName: col.name || col.field || col,
    flex: 1,
    sortable: true,
    filterable: true,
    minWidth: 150,
  }));

  /* -- column order state sync -- (prune missing + merge new, no infinite re-render) */
  const gridFieldSig = JSON.stringify(gridColumns.map(gc => gc.field)); // Stable signature

  useEffect(() => {
    if (!gridColumns.length) return;

    setColumnOrder((prev) => {
    // ⓐ remove columns no longer present
      const stillPresent = prev.filter(c => gridColumns.some(gc => gc.field === c.field));
      // ⓑ append newly-added columns
      const newlyAdded = gridColumns.filter(
        gc => !stillPresent.some(c => c.field === gc.field),
      );

      // Only update if something actually changed
      if (newlyAdded.length || stillPresent.length !== prev.length) {
        return [...stillPresent, ...newlyAdded];
      }
      return prev; // no structural change → keep same reference to avoid loop
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gridFieldSig]);

  /* -- rows mapping -- */
  const gridRows = baseRows.map((row, idx) => ({ id: idx, ...row }));

  const orderedColumns = columnOrder.length ? columnOrder : gridColumns;
  const gridKey = orderedColumns.map(c => `${c.field}-${c.hide ? '0' : '1'}`).join('|');
  /* ── column layout hook ── */


  return (
    <div style={{ width: '100%', overflowX: 'auto' }}>
      <ColumnReorderBar columns={orderedColumns} onReorder={handleBarReorder} queryId={Number(queryId)} />
      <DataGrid
        key={gridKey}
        autoHeight
        rows={gridRows}
        columns={orderedColumns}
        pageSize={pageSize}
        onPageSizeChange={(newPageSize) => setPageSize(newPageSize)}
        rowsPerPageOptions={[5, 10, 25, 50, 100]}
        pagination
        disableSelectionOnClick
        onCellClick={(params, event) => {
          event.stopPropagation();
          handleCellClick(params);
        }}
        components={{ ColumnMenu: CustomColumnMenu }}
        componentsProps={{
          columnMenu: {
            queryId,
            onCreateScope: handleOpenCreateScope,
            onEditScope: handleOpenEditScope,
            scopesList,
            sourceTable,
          },
        }}
      />

      {isCreateScopeOpen && (
        <CreateScope
          open={isCreateScopeOpen}
          onClose={handleCloseCreateScope}
          selectedTable={sourceTable}
          column={selectedColumn || ''}
          tablesMap={tablesMap}
          queriesMap={queriesByName}
          onCreate={handleScopeCreated}
          queryId={Number(queryId)}
        />
      )}

      {isEditScopeOpen && selectedScope && (
        <EditScope
          open={isEditScopeOpen}
          onClose={handleCloseEditScope}
          scope={selectedScope}
          tablesMap={tablesMap}
          onEdit={handleSaveEdit}
          onDelete={handleDeleteScope}
        queriesMap={queriesByName}
        />
      )}
    </div>
  );
};

MuiDatatableRenderer.propTypes = {
  data: PropTypes.shape({
    columns: PropTypes.arrayOf(
      PropTypes.shape({ name: PropTypes.string.isRequired }),
    ).isRequired,
    rows: PropTypes.arrayOf(PropTypes.object).isRequired,
  }).isRequired,
  options: PropTypes.shape({
    rowsPerPage: PropTypes.number,
    filterType: PropTypes.string,
  }).isRequired,
};

/* ──────────────────────────────────  REGISTER  ───────────────────────────────────────── */
registerVisualization({
  type: 'TABLE',
  name: 'Table',
  getOptions: existing => ({ ...DEFAULT_OPTIONS, ...existing }),
  Renderer: MuiDatatableRenderer,
  Editor: MuiDatatableEditor,
  defaultRows: DEFAULT_OPTIONS.rowsPerPage,
  defaultColumns: 10,
});