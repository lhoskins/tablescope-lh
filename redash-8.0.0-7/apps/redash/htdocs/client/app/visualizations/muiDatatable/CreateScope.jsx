/* eslint-disable react/prop-types, react/no-array-index-key */

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
import { currentUser } from '@/services/auth';

// --- Helpers to guarantee columns for target query ---
async function fetchQueryResultColumns(org, qId) {
  try {
    const res = await fetch(`${org}/api/queries/${qId}/results.json?max_age=0`, { credentials: "same-origin" });
    if (!res.ok) return [];
    const j = await res.json();
    if (j.query_result) {
      const cols = (j.query_result.data && j.query_result.data.columns) || [];
      return cols.map(c => c.name || c.friendly_name || c);
    }
    if (j.job) {
      const jobId = j.job.id;
      // poll up to 15s
      for (let i=0;i<15;i++) {
        await new Promise(r => setTimeout(r, 1000));
        const jr = await fetch(`${org}/api/jobs/${jobId}`);
        const jj = await jr.json();
        if (jj.job && jj.job.status === 3) {
          const rid = jj.job.result_id;
          const rr = await fetch(`${org}/api/query_results/${rid}.json`);
          const rj = await rr.json();
          const cols = (rj.data && rj.data.columns) || [];
          return cols.map(c => c.name || c.friendly_name || c);
        }
      }
    }
  } catch(e) { console.error("[CreateScope] fetchQueryResultColumns error", e); }
  return [];
}

/* helper: derive org prefix from URL like  /<org>/query/123 */
function getOrgPrefix() {
  const parts = window.location.pathname.split('/').filter(Boolean);
  // Find the org slug, which is typically before the resource name like 'queries' or 'projects'
  const resourceIndex = parts.findIndex(p => ['queries', 'projects', 'tsqueries'].includes(p));
  if (resourceIndex > 0) {
    return `/${parts.slice(0, resourceIndex).join('/')}`;
  }
  return parts.length ? `/${parts[0]}` : '';
}

const CreateScope = ({
  open,
  onClose,
  column,
  selectedTable,
  onCreate,
  queryId: propQueryId,
  queryName: propQueryName,
}) => {
  /* ───────── local modal state ───────── */
  const [queryId, setQueryId] = useState(null);
  const [queryName, setQueryName] = useState('');
  const [queriesMap, setQueriesMap] = useState({}); // { name → id }
  const [tablesMap, setTablesMap] = useState({}); // { name -> fields[] }

  const [targetTable, setTargetTable] = useState('');
  const [targetField, setTargetField] = useState('');

  /* ───────── reset + fetch every time modal opens ───────── */
  useEffect(() => {
    if (!open) return;

    /* 1️⃣  reset local fields */
    setTargetTable('');
    setTargetField('');
    setQueriesMap({});
    setTablesMap({});

    /* 2️⃣  seed query id / name */
    const gId = window.__queryId || window.__currentQueryId || propQueryId || null;
    const gName = window.__queryName || window.__currentSourceTable || propQueryName || '';

    setQueryId(gId);
    setQueryName(gName);

    /* 3️⃣  fetch ALL queries WITH FIELDS for the current project */
    const projectId = window.__currentProjectId;
    if (projectId) {
      const url = `${getOrgPrefix()}/api/projects/${projectId}/queries_with_field`;
      console.log('[CreateScope] fetching project queries with fields →', url);
      fetch(url)
        .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
        .then((queries) => {
          const qMap = {};
          const tMap = {};
          (queries || []).forEach((q) => {
            if (q.name) {
                qMap[q.name] = q.id;
                tMap[q.name] = q.fields || [];
            }
          });
          setQueriesMap(qMap);
          setTablesMap(tMap);
          console.log('[CreateScope] maps loaded (size =', Object.keys(qMap).length, ')');
        })
        .catch(err => console.error('[CreateScope] queries list error →', err));
    }
  }, [open, propQueryId, propQueryName]);

  /* ───────── selectable lists ───────── */
  const tableNames = Object.keys(tablesMap).sort((a, b) => a.localeCompare(b));
  const availableFields = targetTable ? tablesMap[targetTable] || [] : [];

  // Ensure fields list is populated, try aggressive fallback if empty
  useEffect(() => {
    if (!targetTable) return;
    const have = tablesMap[targetTable];
    if (have && have.length) return;
    const id = queriesMap[targetTable];
    if (!id) return;
    const org = getOrgPrefix();
    (async () => {
      console.log("[CreateScope] fallback: try fetchQueryResultColumns for", targetTable, id);
      const cols = await fetchQueryResultColumns(org, id);
      if (cols && cols.length) {
        setTablesMap(prev => ({ ...prev, [targetTable]: cols }));
        console.log("[CreateScope] loaded cols via results.json", cols);
        alert("Loaded Target Fields for " + targetTable + ": " + JSON.stringify(cols));
      } else {
        console.warn("[CreateScope] still no fields for", targetTable);
      }
    })();
  }, [targetTable, tablesMap, queriesMap]);

  /* ───────── create handler ───────── */
  const handleCreate = async () => {
    const org = getOrgPrefix();
    const payload = {
      project_id: window.__currentProjectId || null,
      query_id: queryId,
      user_id: currentUser.id,
      source_table: selectedTable || window.__currentSourceTable || '',
      source_field: column,
      target_query_id: queriesMap[targetTable],
      target_table: targetTable,
      target_field: targetField,
    };

    console.log('[CreateScope] POST', `${org}/api/scopes`, payload);

    try {
      const res = await fetch(`${org}/api/scopes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        console.error('[CreateScope] server', res.status, await res.text());
        return;
      }
      const body = await res.json();
      console.log('[CreateScope] created OK', body);

      /* bubble up */
      if (body.columns && body.rows) {
        document.dispatchEvent(
          new CustomEvent('scope-created', {
            detail: { columns: body.columns, rows: body.rows },
          }),
        );
      }
      if (onCreate) onCreate(body);

      setTargetTable('');
      setTargetField('');
      onClose();
    } catch (err) {
      console.error('[CreateScope] network error', err);
    }
  };

  /* ───────── render ───────── */
  return (
    <Modal
      open={open}
      onClose={() => {
        setTargetTable('');
        setTargetField('');
        onClose();
      }}
      aria-labelledby="create-scope-modal"
    >
      <Box
        style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          width: 420,
          background: '#fff',
          border: '2px solid #000',
          boxShadow: '0 3px 6px rgba(0,0,0,.16)',
          padding: 32,
        }}
      >
        <Typography id="create-scope-modal" variant="h6">
          Create Scope
        </Typography>

        {/* debug data */}
        <div style={{ fontSize: 12, marginTop: 6, marginBottom: 14, color: '#666' }}>
          <div>
            <strong>Query&nbsp;ID:</strong> {queryId || '(none)'}
          </div>
          <div>
            <strong>Query&nbsp;Name:</strong> {queryName || '(none)'}
          </div>
        </div>

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
              tableNames.map(t => (
                <MenuItem key={t} value={t}>
                  {t}
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

        <Box display="flex" justifyContent="flex-end" mt={2}>
          <Button
            onClick={() => {
              setTargetTable('');
              setTargetField('');
              onClose();
            }}
            style={{ marginRight: 8 }}
          >
            Cancel
          </Button>
          <Button
            variant="contained"
            color="primary"
            disabled={!targetTable || !targetField}
            onClick={handleCreate}
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
  onCreate: PropTypes.func.isRequired,
  queryId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  queryName: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
};

CreateScope.defaultProps = { queryId: null, queryName: '' };

export default CreateScope;