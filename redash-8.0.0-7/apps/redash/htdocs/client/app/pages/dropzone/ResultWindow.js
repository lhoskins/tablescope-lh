/* eslint-disable */

import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';

import {
  DataGrid,
  GridColumnMenuContainer,
  SortGridMenuItems,
  GridFilterMenuItem,
  HideGridColMenuItem,
  GridColumnsMenuItem,
} from '@material-ui/data-grid';
import {
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Typography,
  Box,
  ListItemIcon,
  ListItemText,
} from '@material-ui/core';
import FilterListIcon from '@material-ui/icons/FilterList';
import AddCircleOutlineIcon from '@material-ui/icons/AddCircleOutline';
import CreateScope from './CreateScope';

// Default options for pagination and filter style
const DEFAULT_OPTIONS = { rowsPerPage: 10, filterType: 'dropdown' };

/* ─────────────────────────────────────  OPTIONS EDITOR  ─────────────────────────────────── */
export const MuiDatatableEditor = ({ options, onOptionsChange }) => {
  const handleChange = key => event =>
    onOptionsChange({ ...options, [key]: event.target.value });

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
const CustomColumnMenu = React.forwardRef(function CustomColumnMenu(props, ref) {
  const { hideMenu, currentColumn, onCreateScope } = props;

  const handleCreateScopeClick = evt => {
    if (onCreateScope) onCreateScope(currentColumn.field);
    hideMenu(evt);
  };

  return (
    <GridColumnMenuContainer ref={ref} {...props}>
      <SortGridMenuItems column={currentColumn} onClick={hideMenu} />
      <GridFilterMenuItem column={currentColumn} onClick={hideMenu} />
      <HideGridColMenuItem column={currentColumn} onClick={hideMenu} />
      <MenuItem onClick={handleCreateScopeClick}>
        <ListItemIcon>
          <AddCircleOutlineIcon fontSize="small" />
        </ListItemIcon>
        <ListItemText primary="Create Scope" />
      </MenuItem>
      <GridColumnsMenuItem column={currentColumn} onClick={hideMenu} />
    </GridColumnMenuContainer>
  );
});

CustomColumnMenu.propTypes = {
  hideMenu: PropTypes.func.isRequired,
  currentColumn: PropTypes.shape({ field: PropTypes.string.isRequired }).isRequired,
  onCreateScope: PropTypes.func,
};
CustomColumnMenu.defaultProps = { onCreateScope: null };

/* ─────────────────────────────────────  RENDERER  ─────────────────────────────────────── */
export const MuiDatatableRenderer = ({ data, options }) => {
  const [sourceTable, setSourceTable] = useState(window.__currentSourceTable || '');
  const [tablesList, setTablesList] = useState({ myViews: [], myTables: [] });
  const [isCreateScopeOpen, setIsCreateScopeOpen] = useState(false);
  const [selectedColumn, setSelectedColumn] = useState(null);

  /* ----------  org-prefix & query-id helpers  --------- */
  const pathParts = window.location.pathname.split('/').filter(Boolean);
  const idxToken = pathParts.findIndex(p => /^(?:queries|t[sc]queries)$/.test(p));
  const orgPrefix = idxToken > 0 ? `/${pathParts.slice(0, idxToken).join('/')}` : '';
  const queryId =
    idxToken !== -1 &&
    pathParts[idxToken + 1] &&
    /^\d+$/.test(pathParts[idxToken + 1])
      ? pathParts[idxToken + 1]
      : null;
  /* ---------------------------------------------------- */

  const fetchTableFromQueryAPI = async () => {
    if (!queryId) return '';
    try {
      const res = await fetch(`${orgPrefix}/api/queries/${queryId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      const sql = json.query || '';
      const m = /\bfrom\s+[`"'\[]*([A-Za-z0-9_.]+)[`"'\]]*/i.exec(sql);
      return m ? m[1] : '';
    } catch (err) {
      console.error('ResultWindow: fetchTableFromQueryAPI error:', err);
      return '';
    }
  };

  /* 1) background attempt on mount */
  useEffect(() => {
    if (!queryId) return;
    fetchTableFromQueryAPI().then(tbl => {
      if (tbl) {
        setSourceTable(tbl);
        window.__currentSourceTable = tbl;
      }
    });
  }, []);

  /* 2) listen for Angular broadcast */
  useEffect(() => {
    const handler = e => {
      if (e.detail?.tableName) {
        setSourceTable(e.detail.tableName);
        window.__currentSourceTable = e.detail.tableName;
      }
    };
    document.addEventListener('source-table-detected', handler);
    return () => document.removeEventListener('source-table-detected', handler);
  }, []);

  /* 3) fetch accessible tables (prefix aware) */
  useEffect(() => {
    fetch(`${orgPrefix}/api/TeiidExcelImporterTest/getAccessibleTables`)
      .then(r => (r.ok ? r.json() : {}))
      .then(({ myViews = [], myTables = [] }) => setTablesList({ myViews, myTables }))
      .catch(err => console.error('ResultWindow: tables list fetch error', err));
  }, []);

  /* 4) create-scope menu handler */
  const handleOpenCreateScope = async columnName => {
    let effective = sourceTable || window.__currentSourceTable || '';
    if (!effective && queryId) {
      effective = await fetchTableFromQueryAPI();
      if (effective) {
        setSourceTable(effective);
        window.__currentSourceTable = effective;
      }
    }
    setSelectedColumn(columnName);
    setIsCreateScopeOpen(true);
  };
  const handleCloseCreateScope = () => setIsCreateScopeOpen(false);

  const gridColumns = data.columns.map(col => ({
    field: col.name,
    headerName: col.name,
    flex: 1,
    sortable: true,
    filterable: true,
    minWidth: 150,
  }));
  const gridRows = data.rows.map((row, idx) => ({ id: idx, ...row }));

  return (
    <div style={{ width: '100%', backgroundColor: '#ffffff' }}>
      <DataGrid
        autoHeight
        rows={gridRows}
        columns={gridColumns}
        pageSize={options.rowsPerPage}
        rowsPerPageOptions={[5, 10, 25, 50, 100]}
        pagination
        disableSelectionOnClick
        components={{ ColumnMenu: CustomColumnMenu }}
        componentsProps={{ columnMenu: { onCreateScope: handleOpenCreateScope } }}
      />

      {isCreateScopeOpen && (
        <CreateScope
          open={isCreateScopeOpen}
          onClose={handleCloseCreateScope}
          selectedTable={sourceTable}
          column={selectedColumn || ''}
          tablesList={tablesList}
          onCreate={handleCloseCreateScope}
        />
      )}
    </div>
  );
};

MuiDatatableRenderer.propTypes = {
  data: PropTypes.shape({
    columns: PropTypes.arrayOf(
      PropTypes.shape({ name: PropTypes.string.isRequired })
    ).isRequired,
    rows: PropTypes.arrayOf(PropTypes.object).isRequired,
  }).isRequired,
  options: PropTypes.shape({
    rowsPerPage: PropTypes.number,
    filterType: PropTypes.string,
  }).isRequired,
};

// Wrapper component to accept jsonData prop and render the table
const ResultWindow = ({ jsonData }) => {
  // Build the data shape expected by MuiDatatableRenderer
  const columns =
    Array.isArray(jsonData) && jsonData.length > 0
      ? Object.keys(jsonData[0]).map(name => ({ name }))
      : [];
  const rows = Array.isArray(jsonData) ? jsonData : [];
  const data = { columns, rows };

  return <MuiDatatableRenderer data={data} options={DEFAULT_OPTIONS} />;
};

ResultWindow.propTypes = {
  jsonData: PropTypes.arrayOf(PropTypes.object).isRequired,
};

export default ResultWindow;
