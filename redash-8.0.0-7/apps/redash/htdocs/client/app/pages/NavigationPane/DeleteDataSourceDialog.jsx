import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  CircularProgress,
  Box,
} from '@material-ui/core';
import WarningIcon from '@material-ui/icons/Warning';

const getOrgSlug = () => window.location.pathname.split('/')[1] || 'default';

const formatDate = (dateString) => {
  if (!dateString) return 'Never';
  const date = new Date(dateString);
  return date.toLocaleString();
};

export default function DeleteDataSourceDialog({ open, dataSource, onClose, onConfirm }) {
  const [queries, setQueries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (open && dataSource) {
      setLoading(true);
      setError(null);
      
      const dsId = dataSource.data_source_id || dataSource.id;
      const orgSlug = getOrgSlug();
      
      fetch(`/${orgSlug}/api/data_sources/${dsId}/queries`)
        .then(r => r.ok ? r.json() : Promise.reject(`Failed to fetch queries: ${r.status}`))
        .then(data => {
          setQueries(data);
          setLoading(false);
        })
        .catch(err => {
          console.error('Error fetching queries:', err);
          setError(String(err));
          setLoading(false);
        });
    }
  }, [open, dataSource]);

  if (!dataSource) return null;

  const handleConfirm = () => {
    onConfirm(dataSource);
    onClose();
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center" gap={1}>
          <WarningIcon color="error" />
          <span>Delete Data Source: {dataSource.name}</span>
        </Box>
      </DialogTitle>
      
      <DialogContent>
        <Typography variant="body1" gutterBottom>
          Are you sure you want to permanently delete this data source?
        </Typography>
        
        <Typography variant="body2" color="error" gutterBottom style={{ marginTop: 16 }}>
          <strong>Warning:</strong> This action cannot be undone.
        </Typography>

        {loading && (
          <Box display="flex" justifyContent="center" padding={3}>
            <CircularProgress />
          </Box>
        )}

        {error && (
          <Typography color="error" style={{ marginTop: 16 }}>
            Error loading queries: {error}
          </Typography>
        )}

        {!loading && !error && queries.length > 0 && (
          <>
            <Typography variant="h6" style={{ marginTop: 24, marginBottom: 12 }}>
              Affected Queries ({queries.length})
            </Typography>
            <Typography variant="body2" color="textSecondary" gutterBottom>
              The following queries use this data source and will become orphaned:
            </Typography>
            
            <TableContainer component={Paper} style={{ marginTop: 12, maxHeight: 400 }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell><strong>Query Name</strong></TableCell>
                    <TableCell><strong>Created By</strong></TableCell>
                    <TableCell><strong>Last Updated</strong></TableCell>
                    <TableCell><strong>Last Executed</strong></TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {queries.map(query => (
                    <TableRow key={query.id}>
                      <TableCell>{query.name}</TableCell>
                      <TableCell>{query.user || 'Unknown'}</TableCell>
                      <TableCell>{formatDate(query.updated_at)}</TableCell>
                      <TableCell>{formatDate(query.last_executed_at)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </>
        )}

        {!loading && !error && queries.length === 0 && (
          <Typography variant="body2" color="textSecondary" style={{ marginTop: 16 }}>
            No queries are currently using this data source.
          </Typography>
        )}
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose} color="default">
          Cancel
        </Button>
        <Button 
          onClick={handleConfirm} 
          color="secondary" 
          variant="contained"
          disabled={loading}
        >
          Delete Data Source
        </Button>
      </DialogActions>
    </Dialog>
  );
}

DeleteDataSourceDialog.propTypes = {
  open: PropTypes.bool.isRequired,
  dataSource: PropTypes.object,
  onClose: PropTypes.func.isRequired,
  onConfirm: PropTypes.func.isRequired,
};
