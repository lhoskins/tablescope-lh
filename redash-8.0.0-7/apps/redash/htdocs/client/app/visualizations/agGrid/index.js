// /opt/redash-8.0.0-7/apps/redash/htdocs/client/app/visualizations/agGrid/index.js
import React from 'react';
import PropTypes from 'prop-types';
import { registerVisualization } from '@/visualizations';
import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/dist/styles/ag-grid.css';
import 'ag-grid-community/dist/styles/ag-theme-alpine.css';

const DEFAULT_OPTIONS = { pageSize: 10 };

export const GridEditor = ({ options, onOptionsChange }) => (
  <div style={{ padding: 8 }}>
    Rows per page:
    <select
      value={options.pageSize}
      onChange={e => onOptionsChange({ ...options, pageSize: +e.target.value })}
    >
      {[5, 10, 25, 50, 100].map(n => (
        <option key={n} value={n}>
          {n}
        </option>
      ))}
    </select>
  </div>
);
GridEditor.propTypes = {
  options: PropTypes.shape({ pageSize: PropTypes.number }).isRequired,
  onOptionsChange: PropTypes.func.isRequired,
};

export const GridRenderer = ({ data: { columns, rows }, options }) => {
  const columnDefs = columns.map(c => ({
    field: c.name,
    headerName: c.name,
    sortable: true,
    filter: true,
    resizable: true,
  }));
  const rowData = rows.map((r, i) => ({ id: i, ...r }));

  return (
    <div className="ag-theme-alpine" style={{ height: 400, width: '100%' }}>
      <AgGridReact
        columnDefs={columnDefs}
        rowData={rowData}
        pagination
        paginationPageSize={options.pageSize}
        suppressRowClickSelection
        getMainMenuItems={(params) => {
          const items = params.defaultItems.slice();
          return [
            ...items,
            'separator',
            {
              name: 'Create Scope',
              action: () => {
                console.log('Create Scope on column', params.column.getColId());
              },
            },
          ];
        }}
      />
    </div>
  );
};
GridRenderer.propTypes = {
  data: PropTypes.shape({
    columns: PropTypes.arrayOf(
      PropTypes.shape({ name: PropTypes.string.isRequired }),
    ).isRequired,
    // eslint-disable-next-line react/forbid-prop-types
    rows: PropTypes.arrayOf(PropTypes.object).isRequired,
  }).isRequired,
  options: PropTypes.shape({ pageSize: PropTypes.number }).isRequired,
};

registerVisualization({
  type: 'ag_grid',
  name: 'AG Grid (Community)',
  getOptions: existing => ({ ...DEFAULT_OPTIONS, ...existing }),
  Renderer: GridRenderer,
  Editor: GridEditor,
  defaultRows: DEFAULT_OPTIONS.pageSize,
  defaultColumns: 10,
});
