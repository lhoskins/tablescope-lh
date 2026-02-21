// /opt/redash-8.0.0-7/apps/redash/htdocs/client/app/visualizations/muiDatatable/CreateScope.jsx
import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import {
  Modal,
  Box,
  TextField,
  Button,
  Typography,
  MenuItem,
  Select,
  FormControl,
  InputLabel,
} from '@material-ui/core';

const CreateScope = ({
  open,
  onClose,
  column,
  selectedTable,
  tablesList = { myViews: [], myTables: [] },
  onCreate,
}) => {
  const [targetTable, setTargetTable] = useState('');
  const [targetField, setTargetField] = useState('');
  const [availableFields, setAvailableFields] = useState([]);

  // Combine both MyViews and MyTables into one list
  const combinedTables = [...tablesList.myViews, ...tablesList.myTables];

  // Fetch fields for the currently selected target table
  const fetchFields = async (tableName) => {
    try {
      const res = await fetch(
        `/api/TeiidExcelImporterTest/getColumns?tables=${tableName}`,
      );
      const fields = await res.json();
      setAvailableFields(fields);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('Error fetching fields:', err);
    }
  };

  useEffect(() => {
    if (targetTable) fetchFields(targetTable);
  }, [targetTable]);

  const handleCreate = async () => {
    try {
      const res = await fetch('/api/TeiidExcelImporterTest/createScope', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sourceTable: selectedTable,
          sourceColumn: column,
          targetTable,
          targetColumn: targetField,
        }),
      });
      if (!res.ok) {
        // eslint-disable-next-line no-console
        console.error('Error creating scope:', res.status, await res.text());
        return;
      }
      const resData = await res.json();
      // eslint-disable-next-line no-console
      console.log('Scope created successfully:', resData);
      onCreate({
        sourceTable: selectedTable,
        sourceField: column,
        targetTable,
        targetField,
      });
      onClose();
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('Error creating scope:', err);
    }
  };

  return (
    <Modal open={open} onClose={onClose} aria-labelledby="create-scope-modal">
      <Box
        /* Inline styles instead of v5 `sx` prop */
        style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          width: 400,
          backgroundColor: '#fff',
          border: '2px solid #000',
          boxShadow: '0px 3px 6px rgba(0,0,0,0.16)',
          padding: 32,
        }}
      >
        <Typography id="create-scope-modal" variant="h6" component="h2">
          Create Scope
        </Typography>

        {/* Read‑only source info */}
        <TextField
          fullWidth
          label="Source Table"
          value={selectedTable}
          margin="normal"
          InputProps={{ readOnly: true }}
        />
        <TextField
          fullWidth
          label="Source Field"
          value={column}
          margin="normal"
          InputProps={{ readOnly: true }}
        />

        {/* Target table dropdown */}
        <FormControl fullWidth margin="normal">
          <InputLabel id="target-table-label">Target Table</InputLabel>
          <Select
            labelId="target-table-label"
            value={targetTable}
            onChange={e => setTargetTable(e.target.value)}
            disabled={combinedTables.length === 0}
          >
            {combinedTables.length === 0 ? (
              <MenuItem disabled>No tables available</MenuItem>
            ) : (
              combinedTables.map(table => (
                <MenuItem key={table} value={table}>
                  {table}
                </MenuItem>
              ))
            )}
          </Select>
        </FormControl>

        {/* Target field dropdown */}
        <FormControl fullWidth margin="normal">
          <InputLabel id="target-field-label">Target Field</InputLabel>
          <Select
            labelId="target-field-label"
            value={targetField}
            onChange={e => setTargetField(e.target.value)}
            disabled={availableFields.length === 0}
          >
            {availableFields.length === 0 ? (
              <MenuItem disabled>No fields available</MenuItem>
            ) : (
              availableFields.map(field => (
                <MenuItem key={field.name} value={field.name}>
                  {field.name}
                </MenuItem>
              ))
            )}
          </Select>
        </FormControl>

        {/* Action buttons */}
        <Box
          display="flex"
          justifyContent="flex-end"
          /* MUI v4 Box supports spacing props directly */
          mt={2}
        >
          <Button onClick={onClose} style={{ marginRight: 8 }}>
            Cancel
          </Button>
          <Button
            variant="contained"
            color="primary"
            onClick={handleCreate}
            disabled={!targetTable || !targetField}
          >
            Create
          </Button>
        </Box>
      </Box>
    </Modal>
  );
};

CreateScope.propTypes = {
  open: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  column: PropTypes.string.isRequired,
  selectedTable: PropTypes.string.isRequired,
  tablesList: PropTypes.shape({
    myViews: PropTypes.arrayOf(PropTypes.string).isRequired,
    myTables: PropTypes.arrayOf(PropTypes.string).isRequired,
  }).isRequired,
  onCreate: PropTypes.func.isRequired,
};

export default CreateScope;
