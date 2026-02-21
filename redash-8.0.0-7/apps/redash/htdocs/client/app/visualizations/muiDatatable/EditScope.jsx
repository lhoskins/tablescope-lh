
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
  IconButton,
} from '@material-ui/core';
import DeleteIcon from '@material-ui/icons/Delete';

// Helper: ensure we can fetch columns if tablesMap has none
async function fetchQueryResultColumns(orgPrefix, qId) {
  try {
    // This endpoint will execute the query if needed and return a result (or a job to poll).
    const res = await fetch(`${orgPrefix}/api/queries/${qId}/results.json?max_age=0`, { credentials: "same-origin" });
    if (!res.ok) return [];
    const json = await res.json();
    // If immediate result is present
    if (json.query_result) {
      const cols = (json.query_result.data && json.query_result.data.columns) || [];
      return cols.map(c => c.name || c.friendly_name || c);
    }
    // Otherwise poll job until finished
    if (json.job) {
      const jobId = json.job.id;
      for (let i = 0; i < 15; i++) {
        await new Promise(r => setTimeout(r, 1000));
        const jr = await fetch(`${orgPrefix}/api/jobs/${jobId}`, { credentials: "same-origin" });
        const jj = await jr.json();
        if (jj.job && jj.job.status === 3) {
          const rid = jj.job.result_id;
          const rr = await fetch(`${orgPrefix}/api/query_results/${rid}.json`, { credentials: "same-origin" });
          const rj = await rr.json();
          const cols = (rj.data && rj.data.columns) || [];
          return cols.map(c => c.name || c.friendly_name || c);
        }
      }
    }
  } catch (e) {
    console.error("[EditScope] fetchQueryResultColumns error", e);
  }
  return [];
}

const EditScope = ({
  open,
  onClose,
  scope,
  tablesMap = {},
  queriesMap = {},
  onEdit,
  onDelete,
}) => {
  const [targetTable, setTargetTable] = useState(scope.target_table);
  const [targetField, setTargetField] = useState(scope.target_field);

  useEffect(() => {
    if (open) {
      setTargetTable(scope.target_table);
      setTargetField(scope.target_field);
    }
  }, [open, scope]);

  // Lazy load fields if missing for chosen target table
  useEffect(() => {
    if (!targetTable) { setAvailableFields([]); return; }
    const fieldsFromProps = tablesMap[targetTable] || [];
    if (fieldsFromProps.length) {
      setAvailableFields(fieldsFromProps);
      return;
    }
    // Fallback: fetch from results
    const id = queriesMap[targetTable];
    if (!id) { setAvailableFields([]); return; }
    const org = getOrgPrefix();
    (async () => {
      console.log("[EditScope] fetching fallback fields for", targetTable, "id:", id);
      const cols = await fetchQueryResultColumns(org, id);
      if (cols && cols.length) {
        setAvailableFields(cols);
        console.log("[EditScope] fallback fields loaded", cols);
      } else {
        console.warn("[EditScope] no fields found for", targetTable);
        setAvailableFields([]);
      }
    })();
  }, [targetTable, tablesMap, queriesMap]);


  const tableNames = Object.keys(tablesMap).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
  const [availableFields, setAvailableFields] = useState([]);

  const getOrgPrefix = () => {
    const parts = window.location.pathname.split('/').filter(Boolean);
    const idxNum = parts.findIndex(p => /^\d+$/.test(p));
    return idxNum > 0
      ? `/${parts.slice(0, idxNum).join('/')}`
      : parts.length
        ? `/${parts[0]}`
        : '';
  };

  const handleSave = async () => {
    const url = `${getOrgPrefix()}/api/scopes/${scope.id}`;
    const payload = {
      target_table: targetTable,
      target_field: targetField,
    };
    const res = await fetch(url, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      console.error('[EditScope] save error →', res.status);
      return;
    }
    const updated = await res.json();
    onEdit(updated);
    onClose();
  };

  const handleDelete = async () => {
    const url = `${getOrgPrefix()}/api/scopes/${scope.id}`;
    const res = await fetch(url, {
      method: 'DELETE',
      credentials: 'same-origin',
    });
    if (!res.ok) {
      console.error('[EditScope] delete error →', res.status);
      return;
    }
    if (onDelete) onDelete(scope.id);
    onClose();
  };

  return (
    <Modal open={open} onClose={onClose} aria-labelledby="edit-scope-modal">
      <Box
        style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          width: 420,
          backgroundColor: '#fff',
          border: '2px solid #000',
          boxShadow: '0px 3px 6px rgba(0,0,0,0.16)',
          padding: 32,
        }}
      >
        <Typography id="edit-scope-modal" variant="h6" gutterBottom>
          Edit Scope
        </Typography>

        <TextField
          fullWidth
          label="Source Table"
          value={scope.source_table}
          margin="normal"
          InputProps={{ readOnly: true }}
        />
        <TextField
          fullWidth
          label="Source Field"
          value={scope.source_field}
          margin="normal"
          InputProps={{ readOnly: true }}
        />

        <FormControl fullWidth margin="normal">
          <InputLabel id="target-table-label">Target Table</InputLabel>
          <Select
            labelId="target-table-label"
            value={targetTable}
            onChange={(e) => {
              setTargetTable(e.target.value);
              setTargetField('');
            }}
            disabled={tableNames.length === 0}
          >
            {tableNames.length === 0 ? (
              <MenuItem disabled>No tables available</MenuItem>
            ) : (
              tableNames.map(name => (
                <MenuItem key={name} value={name}>
                  {name}
                </MenuItem>
              ))
            )}
          </Select>
        </FormControl>

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
              availableFields.map(f => (
                <MenuItem key={f} value={f}>
                  {f}
                </MenuItem>
              ))
            )}
          </Select>
        </FormControl>

        <Box display="flex" justifyContent="space-between" mt={3}>
          <IconButton
            onClick={handleDelete}
            title="Delete scope"
            aria-label="delete"
          >
            <DeleteIcon color="error" />
          </IconButton>

          <Box>
            <Button onClick={onClose} style={{ marginRight: 8 }}>
              Cancel
            </Button>
            <Button
              variant="contained"
              color="primary"
              onClick={handleSave}
              disabled={!targetTable || !targetField}
            >
              Update
            </Button>
          </Box>
        </Box>
      </Box>
    </Modal>
  );
};

EditScope.propTypes = {
  open: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  scope: PropTypes.shape({
    id: PropTypes.number.isRequired,
    source_table: PropTypes.string.isRequired,
    source_field: PropTypes.string.isRequired,
    target_table: PropTypes.string,
    target_field: PropTypes.string,
  }).isRequired,
  tablesMap: PropTypes.objectOf(PropTypes.array).isRequired,
  queriesMap: PropTypes.object,
  onEdit: PropTypes.func.isRequired,
  onDelete: PropTypes.func,
};

EditScope.defaultProps = {
  onDelete: null,
  queriesMap: {},
};

export default EditScope;