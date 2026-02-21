/* eslint-disable react/require-default-props, camelcase */

import React, { useState, useEffect, useMemo } from 'react';
import PropTypes from 'prop-types';
import {
  Box,
  Typography,
  List,
  ListItem,
  Checkbox,
  ListItemIcon,
  ListItemText,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Divider,
} from '@material-ui/core';

/* ─────────────────────────────────────────────── */
/* Helper: build “schema.table.column” identifier  */
/* ─────────────────────────────────────────────── */
const keyOf = (tbl, fld) => `${tbl}.${fld}`;

/* ─────────────────────────────────────────────── */
/* JoinBuilder                                    */
/* ───────────────────────────────────────────────
   Props
   ─────
   ▸ leftTable, rightTable …… currently-selected table names
   ▸ leftFields, rightFields… arrays of query objects or
                               raw string[] of column names
   ▸ hideQuerySelectors ……   when true, table pickers are hidden
   ▸ onChange(payload) ……    callback → TSQueryEditor
     payload = {
       leftTableName,  rightTableName,
       joinType,       joinOperand,     // ★ NEW
       joinClause,
       selectedLeftCols,  selectedRightCols,
       leftAllFields,    rightAllFields,
       leftTableJoinColumn, // ★ NEW
       rightTableJoinColumn // ★ NEW
     }
   The component no longer auto-creates a JOIN clause until both
   operands are chosen by the user. The join type & operator are
   controlled via local state and bubbled up through onChange.
   ─────────────────────────────────────────────── */
export default function JoinBuilder({
  leftTable,
  rightTable,
  leftFields,
  rightFields,
  onChange,
  hideQuerySelectors,
  // NEW PROPS for initial state
  initialJoinType,
  initialJoinOperand,
  initialLeftTableJoinColumn,
  initialRightTableJoinColumn,
}) {
  /* ══════════════════════════════════════════════ */
  /* 1. Normalise the fields arrays                */
  /* ══════════════════════════════════════════════ */
  const normalise = (arr, tblLabel) => {
    if (!arr) return [];
    // If the first item is an object, assume it's the {name, tableName, fields} structure
    if (arr.length && typeof arr[0] === 'object') return arr;
    /* plain strings[] → wrap once so downstream code is uniform */
    return [{ name: tblLabel || 'Table', tableName: tblLabel || 'Table', fields: arr }];
  };

  const queriesLeft = normalise(leftFields, leftTable);
  const queriesRight = normalise(rightFields, rightTable);

  /* ══════════════════════════════════════════════ */
  /* 2.  Which table is active on each side        */
  /* ══════════════════════════════════════════════ */
  const [leftQueryKey, setLeftQueryKey] = useState('');
  const [rightQueryKey, setRightQueryKey] = useState('');

  const emptyQueryObj = { name: '', tableName: '', fields: [] };

  const activeLeftQuery = useMemo(
    () => queriesLeft.find(q => (q.tableName || q.name) === leftQueryKey) || emptyQueryObj,
    [queriesLeft, leftQueryKey],
  );
  const activeRightQuery = useMemo(
    () => queriesRight.find(q => (q.tableName || q.name) === rightQueryKey) || emptyQueryObj,
    [queriesRight, rightQueryKey],
  );

  /* If parent hides selectors, keep our keys synced with props */
  useEffect(() => {
    if (hideQuerySelectors) {
      setLeftQueryKey(leftTable);
      setRightQueryKey(rightTable);
    }
  }, [leftTable, rightTable, hideQuerySelectors]);

  /* ══════════════════════════════════════════════ */
  /* 3. Column selections                          */
  /* ══════════════════════════════════════════════ */
  const [selectedLeftCols, setSelectedLeftCols] = useState([]);
  const [selectedRightCols, setSelectedRightCols] = useState([]);

  const toggleFieldLocal = (side, tbl, fld) => {
    const full = keyOf(tbl, fld);
    if (side === 'left') {
      setSelectedLeftCols(prev => (prev.includes(full) ? prev.filter(x => x !== full) : [...prev, full]));
    } else {
      setSelectedRightCols(prev => (prev.includes(full) ? prev.filter(x => x !== full) : [...prev, full]));
    }
  };

  /* ══════════════════════════════════════════════ */
  /* 4. Join metadata controlled by user           */
  /* ══════════════════════════════════════════════ */
  // Initialize with new props or defaults
  const [joinType, setJoinType] = useState(initialJoinType || 'INNER');
  const [joinOperand, setJoinOperand] = useState(initialJoinOperand || '=');
  const [leftTableJoinColumn, setLeftTableJoinColumn] = useState(initialLeftTableJoinColumn || '');
  const [rightTableJoinColumn, setRightTableJoinColumn] = useState(initialRightTableJoinColumn || '');

  // Effect to update local state when initial props change (on query load)
  useEffect(() => {
    setJoinType(initialJoinType || 'INNER');
    setJoinOperand(initialJoinOperand || '=');
    setLeftTableJoinColumn(initialLeftTableJoinColumn || '');
    setRightTableJoinColumn(initialRightTableJoinColumn || '');
  }, [initialJoinType, initialJoinOperand, initialLeftTableJoinColumn, initialRightTableJoinColumn]);


  /* ══════════════════════════════════════════════ */
  /* 5. Notify parent whenever anything changes    */
  /* ══════════════════════════════════════════════ */
  useEffect(() => {
    /* Build JOIN only when both operands exist */
    let clause = '';
    if (leftTableJoinColumn && rightTableJoinColumn) {
      // Ensure rightTable is correctly derived, could be from activeRightQuery.tableName or prop
      const rightTbl = activeRightQuery.tableName || rightTable; 
      clause = `${joinType.toUpperCase()} JOIN ${rightTbl} ON ${leftTableJoinColumn} ${joinOperand} ${rightTableJoinColumn}`;
    }

    const payload = {
      leftTableName: activeLeftQuery.tableName || '',
      rightTableName: activeRightQuery.tableName || '',
      joinType,
      joinConditionOperand: joinOperand,
      explicitJoinClause: clause, // Send the fully-formed clause
      joinClause: clause, // Renamed to joinClause for consistency with TSQueryEditor
      leftTableJoinColumn, // Send the chosen left operand column
      rightTableJoinColumn, // Send the chosen right operand column
      selectedLeftCols,
      selectedRightCols,
      leftAllFields: (activeLeftQuery.fields || []).map(f => keyOf(activeLeftQuery.tableName, f)),
      rightAllFields: (activeRightQuery.fields || []).map(f => keyOf(activeRightQuery.tableName, f)),
    };

    // Only call onChange if there's a meaningful change to avoid infinite loops
    // This comparison is crucial. We need to compare the *current* payload with the *last sent* payload.
    // However, since we don't store the last sent payload in JoinBuilder's state,
    // we rely on TSQueryEditor's `handleJoinChange` to do the `isEqual` check.
    // So, we always call onChange, and let the parent decide if it's a "no-op" change.
    onChange(payload);

  }, [
    activeLeftQuery,
    activeRightQuery,
    leftTableJoinColumn,
    rightTableJoinColumn,
    joinType,
    joinOperand,
    selectedLeftCols,
    selectedRightCols,
    onChange,
    rightTable, // Include rightTable prop in dependencies
  ]);

  /* ══════════════════════════════════════════════ */
  /* 6. Render helpers                             */
  /* ══════════════════════════════════════════════ */
  const renderFieldList = (side, queryObj, selectedArr) => (
    <Box style={{ maxHeight: '40vh', overflowY: 'auto' }}>
      <List dense>
        {(queryObj.fields || []).map((f) => {
          const full = keyOf(queryObj.tableName || queryObj.name, f);
          return (
            <ListItem
              key={full}
              button
              onClick={() => toggleFieldLocal(side, queryObj.tableName || queryObj.name, f)}
            >
              <ListItemIcon>
                <Checkbox edge="start" checked={selectedArr.includes(full)} />
              </ListItemIcon>
              <ListItemText primary={f} />
            </ListItem>
          );
        })}
      </List>
    </Box>
  );

  /* ══════════════════════════════════════════════ */
  /* 7. UI                                         */
  /* ══════════════════════════════════════════════ */
  return (
    <Box display="flex" height="100%">
      {/* ◀ LEFT table / columns */}
      {!hideQuerySelectors && (
        <Box flex={1} p={2} style={{ borderRight: '1px solid #ddd' }}>
          <Typography variant="subtitle1" gutterBottom>
            Left&nbsp;Query
          </Typography>

          <FormControl variant="outlined" fullWidth size="small" margin="dense">
            <InputLabel>Select Table</InputLabel>
            <Select
              label="Select Table"
              value={leftQueryKey}
              onChange={e => setLeftQueryKey(e.target.value)}
            >
              <MenuItem value="">
                <em>Select&nbsp;Table</em>
              </MenuItem>
              {queriesLeft.map((q) => {
                const val = q.tableName || q.name;
                return (
                  <MenuItem key={val} value={val}>
                    {q.name}
                  </MenuItem>
                );
              })}
            </Select>
          </FormControl>

          <Divider style={{ margin: '8px 0' }} />

          {renderFieldList('left', activeLeftQuery, selectedLeftCols)}
        </Box>
      )}

      {/* ◈ Relation Properties (always visible) */}
      <Box flex={1} p={2}>
        <Typography variant="subtitle1" gutterBottom>
          Relation&nbsp;Properties
        </Typography>

        {/* Left operand (column) */}
        <FormControl fullWidth margin="dense" size="small" variant="outlined">
          <InputLabel>Left Column</InputLabel>
          <Select
            label="Left Column"
            value={leftTableJoinColumn}
            displayEmpty
            onChange={e => setLeftTableJoinColumn(e.target.value)}
          >
            <MenuItem value="">
              <em>Select Column</em>
            </MenuItem>
            {(activeLeftQuery.fields || []).map((fld) => {
              const val = keyOf(activeLeftQuery.tableName, fld);
              return (
                <MenuItem key={val} value={val}>
                  {val}
                </MenuItem>
              );
            })}
          </Select>
        </FormControl>

        {/* Right operand (column) */}
        <FormControl fullWidth margin="dense" size="small" variant="outlined">
          <InputLabel>Right Column</InputLabel>
          <Select
            label="Right Column"
            value={rightTableJoinColumn}
            displayEmpty
            onChange={e => setRightTableJoinColumn(e.target.value)}
          >
            <MenuItem value="">
              <em>Select Column</em>
            </MenuItem>
            {(activeRightQuery.fields || []).map((fld) => {
              const val = keyOf(activeRightQuery.tableName, fld);
              return (
                <MenuItem key={val} value={val}>
                  {val}
                </MenuItem>
              );
            })}
          </Select>
        </FormControl>

        {/* Join type selector */}
        <FormControl fullWidth margin="dense" size="small" variant="outlined">
          <InputLabel>Join Type</InputLabel>
          <Select
            label="Join Type"
            value={joinType}
            onChange={e => setJoinType(e.target.value)}
          >
            <MenuItem value="INNER">Inner&nbsp;Join</MenuItem>
            <MenuItem value="LEFT">Left&nbsp;Join</MenuItem>
            <MenuItem value="RIGHT">Right&nbsp;Join</MenuItem>
            <MenuItem value="FULL">Full&nbsp;Join</MenuItem>
          </Select>
        </FormControl>

        {/* Operator selector */}
        <FormControl fullWidth margin="dense" size="small" variant="outlined">
          <InputLabel>Operator</InputLabel>
          <Select
            label="Operator"
            value={joinOperand}
            onChange={e => setJoinOperand(e.target.value)}
          >
            <MenuItem value="=">=&nbsp;Equals</MenuItem>
            <MenuItem value="<>">&lt;&gt;&nbsp;Not&nbsp;Equals</MenuItem>
            <MenuItem value=">">&gt;&nbsp;Greater&nbsp;Than</MenuItem>
            <MenuItem value="<">&lt;&nbsp;Less&nbsp;Than</MenuItem>
            <MenuItem value="<=">&lt;=&nbsp;Less&nbsp;Than&nbsp;or&nbsp;Equals</MenuItem>
            <MenuItem value=">=">&gt;=&nbsp;Greater&nbsp;Than&nbsp;or&nbsp;Equals</MenuItem>
          </Select>
        </FormControl>
      </Box>

      {/* ▶ RIGHT table / columns */}
      {!hideQuerySelectors && (
        <Box flex={1} p={2} style={{ borderLeft: '1px solid #ddd' }}>
          <Typography variant="subtitle1" gutterBottom>
            Right&nbsp;Query
          </Typography>

          <FormControl variant="outlined" fullWidth size="small" margin="dense">
            <InputLabel>Select Table</InputLabel>
            <Select
              label="Select Table"
              value={rightQueryKey}
              onChange={e => setRightQueryKey(e.target.value)}
            >
              <MenuItem value="">
                <em>Select&nbsp;Table</em>
              </MenuItem>
              {queriesRight.map((q) => {
                const val = q.tableName || q.name;
                return (
                  <MenuItem key={val} value={val}>
                    {q.name}
                  </MenuItem>
                );
              })}
            </Select>
          </FormControl>

          <Divider style={{ margin: '8px 0' }} />

          {renderFieldList('right', activeRightQuery, selectedRightCols)}
        </Box>
      )}
    </Box>
  );
}

/* ─────────────────────────────────────────────── */
/* PropTypes / Defaults                            */
/* ─────────────────────────────────────────────── */
JoinBuilder.propTypes = {
  leftTable: PropTypes.string,
  rightTable: PropTypes.string,
  leftFields: PropTypes.array,
  rightFields: PropTypes.array,
  onChange: PropTypes.func,
  hideQuerySelectors: PropTypes.bool,
  initialJoinType: PropTypes.string, // NEW
  initialJoinOperand: PropTypes.string, // NEW
  initialLeftTableJoinColumn: PropTypes.string, // NEW
  initialRightTableJoinColumn: PropTypes.string, // NEW
};

JoinBuilder.defaultProps = {
  leftTable: '',
  rightTable: '',
  leftFields: [],
  rightFields: [],
  onChange: () => {},
  hideQuerySelectors: false,
  initialJoinType: 'INNER', // Default
  initialJoinOperand: '=', // Default
  initialLeftTableJoinColumn: '', // Default
  initialRightTableJoinColumn: '', // Default
};
