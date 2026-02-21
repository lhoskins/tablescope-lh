/* eslint-disable */
/* eslint-disable react/require-default-props, camelcase, class-methods-use-this, react/sort-comp */

import React from 'react';
import PropTypes from 'prop-types';
import { Box, Typography, TextField, IconButton, FormControlLabel, Checkbox } from '@material-ui/core';
import CloseIcon from '@material-ui/icons/Close';
import { DataGrid } from '@material-ui/data-grid';
import { QueryBuilder, formatQuery } from 'react-querybuilder';
import 'react-querybuilder/dist/query-builder.css';

/* ------------------------------------------------------------------ */
/* ★ NEW – MUI controls for React Query Builder grid                 */
/* ------------------------------------------------------------------ */
/* ─── FIELD SELECTOR ───────────────────────────────────────────── */
const FieldSelector = ({ options = [], value, handleOnChange }) => (
  <select
    value={value}
    onChange={(e) => handleOnChange(e.target.value)}
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
    {options.map((o) => (
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
    onChange={(e) => handleOnChange(e.target.value)}
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
    {options.map((o) => (
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
  <TextField
    value={value}
    size="small"
    variant="outlined"
    fullWidth
    onChange={(e) => handleOnChange(e.target.value)}
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
    onChange={(e) => handleOnChange(e.target.value)}
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
    {options.map((o) => (
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
  <IconButton size="small" onClick={handleOnClick}>
    <CloseIcon fontSize="small" />
  </IconButton>
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
/**
 * Rudimentary parser to extract column list from a SQL SELECT string.
 * Assumes form: SELECT col1, col2, ... FROM <table> WHERE ...
 */
const extractSelectedFields = (sql) => {
  if (!sql) return [];
  const selectMatch = sql.match(/select\s+([\s\S]+?)\s+from/i);
  if (!selectMatch) return [];
  const colsPart = selectMatch[1];
  return colsPart
    .split(',')
    .map((c) => c.trim())
    .filter((c) => c !== '*' && c.length);
};

/**
 * Rudimentary parser to extract simple WHERE clauses connected by AND.
 * Only handles conditions of form: <field> <op> <value> (no OR, no parentheses).
 */
const extractWhereRules = (sql, tableName) => {
  if (!sql) return { combinator: 'and', rules: [] };
  const whereMatch = sql.match(/where\s+([\s\S]+)$/i);
  if (!whereMatch) return { combinator: 'and', rules: [] };
  const condStr = whereMatch[1].trim();
  // Split on AND
  const parts = condStr.split(/\s+and\s+/i);
  const rules = parts.map((part) => {
    const m = part.match(/([\w.]+)\s*(=|<>|<|>|<=|>=|like)\s*(.+)/i);
    if (m) {
      let [, field, operator, value] = m;
      value = value.trim().replace(/;$/, ''); // remove trailing semicolon
      // Strip quotes if present
      if ((value.startsWith("'") && value.endsWith("'")) || (value.startsWith('"') && value.endsWith('"'))) {
        value = value.slice(1, -1);
      }
      // Prefix field with tableName if no dot present
      if (!field.includes('.')) {
        field = `${tableName}.${field}`;
      }
      return { field, operator, value };
    }
    return null;
  });
  return { combinator: 'and', rules: rules.filter((r) => r !== null) };
};

/**
 * Builds RQB-compatible field options from preview columns.
 * Each field is prefixed with tableName.
 */
const buildRQBFields = (columns, tableName) =>
  columns.map((c) => ({
    name: `${tableName}.${c.field}`,
    label: `${tableName}.${c.field}`,
  }));

/* ------------------------------------------------------------------ */
/* Component: EditTable                                               */
/* ------------------------------------------------------------------ */
class EditTable extends React.Component {
  static propTypes = {
    tableName: PropTypes.string.isRequired,
    preview: PropTypes.shape({
      columns: PropTypes.arrayOf(
        PropTypes.shape({
          field: PropTypes.string.isRequired,
          headerName: PropTypes.string,
        })
      ),
      rows: PropTypes.arrayOf(PropTypes.object),
    }).isRequired,
    initialQueryText: PropTypes.string.isRequired,
    onUpdate: PropTypes.func.isRequired, // Called with updated SQL when rules/fields change
  };

  constructor(props) {
    super(props);

    const { preview, initialQueryText, tableName } = this.props;

    // Extract fields in SELECT clause
    const selectedColsRaw = extractSelectedFields(initialQueryText);
    const selectedFields = selectedColsRaw.map((col) => {
      // If not prefixed, add tableName prefix
      if (col.includes('.')) return col;
      return `${tableName}.${col}`;
    });

    // Build initial ruleTree from WHERE clause
    const initialRuleTree = extractWhereRules(initialQueryText, tableName);

    // Available RQB fields
    const rqbFields = buildRQBFields(preview.columns, tableName);

    this.state = {
      selectedColumns: selectedFields, // array of strings: "tableName.column"
      ruleTree: initialRuleTree, // { combinator: 'and', rules: [...] }
      rqbFields,
    };

    this.handleRuleChange = this.handleRuleChange.bind(this);
    this.toggleColumn = this.toggleColumn.bind(this);
    this.updateSQLFromVisual = this.updateSQLFromVisual.bind(this);
  }

  componentDidUpdate(prevProps, prevState) {
    // When ruleTree or selectedColumns change, rebuild SQL and call onUpdate
    if (
      prevState.ruleTree !== this.state.ruleTree ||
      prevState.selectedColumns !== this.state.selectedColumns
    ) {
      this.updateSQLFromVisual();
    }
  }

  /**
   * Reconstruct SQL from selectedColumns and ruleTree, then notify parent.
   */
  updateSQLFromVisual() {
    const { tableName } = this.props;
    const { selectedColumns, ruleTree } = this.state;

    // Build SELECT clause
    const selectClause =
      selectedColumns.length > 0
        ? selectedColumns.map((f) => f.replace(`${tableName}.`, '')).join(', ')
        : '*';

    // Build WHERE clause from ruleTree
    let whereClause = '';
    if (ruleTree.rules && ruleTree.rules.length > 0) {
      // Use formatQuery, but we need to strip table prefix in the field names for formatQuery,
      // then re-add them after. Simpler: build manually.
      const conditions = ruleTree.rules.map((r) => {
        // r.field is like "tableName.column"
        const fieldOnly = r.field.startsWith(`${tableName}.`)
          ? r.field.slice(tableName.length + 1)
          : r.field;
        const valueStr = isNaN(r.value) ? `'${r.value}'` : r.value;
        return `${fieldOnly} ${r.operator} ${valueStr}`;
      });
      whereClause = ` WHERE ${conditions.join(' AND ')}`;
    }

    const newSQL = `SELECT ${selectClause} FROM ${tableName}${whereClause}`;
    this.props.onUpdate(newSQL);
  }

  handleRuleChange(newTree) {
    this.setState({ ruleTree: newTree });
  }

  toggleColumn(colKey) {
    this.setState((state) => {
      const { selectedColumns } = state;
      if (selectedColumns.includes(colKey)) {
        return {
          selectedColumns: selectedColumns.filter((c) => c !== colKey),
        };
      }
      return {
        selectedColumns: [...selectedColumns, colKey],
      };
    });
  }

  render() {
    const { preview, tableName } = this.props;
    const { selectedColumns, ruleTree, rqbFields } = this.state;

    // Prepare DataGrid columns with headerClassName to highlight selected
    const preparedColumns = preview.columns.map((col) => {
      const fullKey = `${tableName}.${col.field}`;
      return {
        ...col,
        sortable: false,
        headerClassName: () =>
          selectedColumns.includes(fullKey) ? 'selected-header' : '',
      };
    });

    return (
      <Box display="flex" flexDirection="column" height="100%" overflow="auto">
        {/* TABLE COLUMNS PREVIEW */}
        <Box flex="0 0 auto" p={2}>
          <Typography variant="subtitle1" style={{ fontWeight: 'bold', fontSize: '1.5rem' }}>
            {tableName} Columns
          </Typography>
          <div style={{ height: 300, width: '100%' }}>
            <DataGrid
              rows={preview.rows}
              columns={preparedColumns}
              pageSize={5}
              rowsPerPageOptions={[5]}
              hideFooterSelectedRowCount
              disableColumnMenu
              onColumnHeaderClick={(params) => {
                const fullKey = `${tableName}.${params.field}`;
                this.toggleColumn(fullKey);
              }}
            />
          </div>
        </Box>

        {/* RULES / GROUP WINDOW */}
        <Box flex="1 1 auto" overflow="auto" p={2}>
          <Typography variant="subtitle1" style={{ fontWeight: 'bold', fontSize: '1.5rem' }}>
            Filter Rules
          </Typography>
          <QueryBuilder
            fields={rqbFields}
            query={ruleTree}
            onQueryChange={this.handleRuleChange}
            controlElements={rqbControls}
            controlClassnames={{ rule: 'rqb-rule-grid' }}
            showAddGroupAction={false}
            showAddRuleAction={false}
            showCombinatorsBetweenRules
          />
        </Box>
      </Box>
    );
  }
}

export default EditTable;
