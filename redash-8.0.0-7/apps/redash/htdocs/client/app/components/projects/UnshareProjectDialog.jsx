import React, { useState, useEffect } from 'react';
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
  Divider,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/core/styles';
import WarningIcon from '@material-ui/icons/Warning';
import LockIcon from '@material-ui/icons/Lock';
import ErrorIcon from '@material-ui/icons/Error';

const useStyles = makeStyles((theme) => ({
  dialogTitle: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(1),
  },
  warningIcon: {
    color: theme.palette.warning.main,
  },
  tableContainer: {
    maxHeight: 200,
    marginTop: theme.spacing(1),
    marginBottom: theme.spacing(2),
  },
  sectionTitle: {
    fontWeight: 600,
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(1),
  },
  warningBox: {
    backgroundColor: '#fff3e0',
    border: '1px solid #ff9800',
    borderRadius: 4,
    padding: theme.spacing(2),
    marginBottom: theme.spacing(2),
    display: 'flex',
    alignItems: 'flex-start',
    gap: theme.spacing(1),
  },
  errorBox: {
    backgroundColor: '#ffebee',
    border: '1px solid #f44336',
    borderRadius: 4,
    padding: theme.spacing(2),
    marginBottom: theme.spacing(2),
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  unshareButton: {
    backgroundColor: theme.palette.error.main,
    color: theme.palette.common.white,
    '&:hover': {
      backgroundColor: theme.palette.error.dark,
    },
  },
}));

/* Helper: derive org slug from URL → /<org>/something */
const getOrgSlug = () => window.location.pathname.split('/')[1] || 'default';

function UnshareProjectDialog({ open, projectId, projectName, onClose, onSuccess }) {
  const classes = useStyles();
  const [loading, setLoading] = useState(false);
  const [unsharing, setUnsharing] = useState(false);
  const [error, setError] = useState(null);
  const [impactData, setImpactData] = useState({
    members: [],
    queries: [],
    datasources: [],
  });

  // Fetch impact data when dialog opens
  useEffect(() => {
    if (open && projectId) {
      fetchImpactData();
    }
  }, [open, projectId]);

  const fetchImpactData = async () => {
    setLoading(true);
    setError(null);

    try {
      const orgSlug = getOrgSlug();
      const response = await fetch(`/${orgSlug}/api/projects/${projectId}/unshare/impact`);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || errorData.message || `HTTP ${response.status}`);
      }

      const data = await response.json();
      setImpactData(data);
    } catch (err) {
      console.error('Error fetching unshare impact data:', err);
      setError(err.message || 'Failed to fetch impact data');
    } finally {
      setLoading(false);
    }
  };

  const handleUnshare = async () => {
    setUnsharing(true);
    setError(null);

    try {
      const orgSlug = getOrgSlug();
      const response = await fetch(`/${orgSlug}/api/projects/${projectId}/unshare`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ confirm: true }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || errorData.message || `HTTP ${response.status}`);
      }

      const result = await response.json();

      if (result.success) {
        // Close dialog first to prevent React rendering issues
        onClose();
        
        // Call success callback to refresh project data
        if (onSuccess) {
          onSuccess(result);
        }
      } else {
        throw new Error(result.error || 'Unshare operation failed');
      }
    } catch (err) {
      console.error('Error unsharing project:', err);
      setError(err.message || 'Failed to unshare project');
    } finally {
      setUnsharing(false);
    }
  };

  const handleClose = (event, reason) => {
    // Prevent closing during unshare operation
    if (unsharing) {
      return;
    }
    // Prevent closing by backdrop click or escape key during operation
    if (reason === 'backdropClick' || reason === 'escapeKeyDown') {
      return;
    }
    setError(null);
    onClose();
  };

  const formatDate = (dateString) => {
    if (!dateString) return 'N/A';
    try {
      return new Date(dateString).toLocaleDateString();
    } catch {
      return 'N/A';
    }
  };

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      maxWidth="md"
      fullWidth
    >
      <DialogTitle>
        <div className={classes.dialogTitle}>
          <WarningIcon className={classes.warningIcon} />
          <span>Unshare Project: {projectName}</span>
        </div>
      </DialogTitle>

      <DialogContent>
        {/* Warning Message */}
        <Box className={classes.warningBox}>
          <WarningIcon style={{ color: '#ff9800', marginTop: 2 }} />
          <Box>
            <Typography variant="body2" gutterBottom>
              <strong>Are you sure you want to unshare this project?</strong>
            </Typography>
            <Typography variant="body2" component="div">
              This will:
              <ul style={{ marginTop: 8, marginBottom: 8 }}>
                <li>Remove all members except you</li>
                <li>Execute data migration to private ownership</li>
                <li>Convert project to private status</li>
              </ul>
            </Typography>
            <Typography variant="body2" style={{ color: '#f44336' }}>
              <strong>⚠️ Warning: This process may take several minutes to complete.</strong>
            </Typography>
          </Box>
        </Box>

        {/* Error Display */}
        {error && (
          <Box className={classes.errorBox}>
            <Box display="flex" alignItems="center" style={{ gap: 8 }}>
              <ErrorIcon style={{ color: '#f44336' }} />
              <Typography variant="body2" style={{ color: '#f44336' }}>
                {error}
              </Typography>
            </Box>
            <Button size="small" onClick={fetchImpactData} disabled={loading}>
              Retry
            </Button>
          </Box>
        )}

        {/* Loading State */}
        {loading && (
          <Box display="flex" flexDirection="column" alignItems="center" py={4}>
            <CircularProgress />
            <Typography variant="body2" style={{ marginTop: 16 }}>
              Loading impact data...
            </Typography>
          </Box>
        )}

        {/* Impact Data Tables */}
        {!loading && !error && (
          <div>
            {/* Members Table */}
            <Typography variant="h6" className={classes.sectionTitle}>
              {impactData.members.length} Member{impactData.members.length !== 1 ? 's' : ''} Will Be
              Removed
            </Typography>
            {impactData.members.length > 0 ? (
              <TableContainer component={Paper} className={classes.tableContainer}>
                <Table size="small" stickyHeader>
                  <TableHead>
                    <TableRow>
                      <TableCell>Name</TableCell>
                      <TableCell>Email</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {impactData.members.map((member) => (
                      <TableRow key={member.id}>
                        <TableCell>{member.name}</TableCell>
                        <TableCell>{member.email}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            ) : (
              <Typography variant="body2" color="textSecondary">
                No members to remove (you are the only member)
              </Typography>
            )}

            <Divider style={{ margin: '16px 0' }} />

            {/* Queries Table */}
            <Typography variant="h6" className={classes.sectionTitle}>
              {impactData.queries.length} Quer{impactData.queries.length !== 1 ? 'ies' : 'y'} Will Be
              Removed From Project
            </Typography>
            {impactData.queries.length > 0 ? (
              <TableContainer component={Paper} className={classes.tableContainer}>
                <Table size="small" stickyHeader>
                  <TableHead>
                    <TableRow>
                      <TableCell>Query Name</TableCell>
                      <TableCell>Created By</TableCell>
                      <TableCell>Last Updated</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {impactData.queries.map((query) => (
                      <TableRow key={query.id}>
                        <TableCell>{query.name}</TableCell>
                        <TableCell>{query.created_by}</TableCell>
                        <TableCell>{formatDate(query.updated_at)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            ) : (
              <Typography variant="body2" color="textSecondary">
                No queries owned by other members
              </Typography>
            )}

            <Divider style={{ margin: '16px 0' }} />

            {/* Datasources Table */}
            <Typography variant="h6" className={classes.sectionTitle}>
              {impactData.datasources.length} Datasource
              {impactData.datasources.length !== 1 ? 's' : ''} Will Be Removed From Project
            </Typography>
            {impactData.datasources.length > 0 ? (
              <TableContainer component={Paper} className={classes.tableContainer}>
                <Table size="small" stickyHeader>
                  <TableHead>
                    <TableRow>
                      <TableCell>Datasource Name</TableCell>
                      <TableCell>Type</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {impactData.datasources.map((datasource) => (
                      <TableRow key={datasource.id}>
                        <TableCell>{datasource.name}</TableCell>
                        <TableCell>{datasource.type}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            ) : (
              <Typography variant="body2" color="textSecondary">
                No datasources owned by other members
              </Typography>
            )}
          </div>
        )}
      </DialogContent>

      <DialogActions>
        <Button onClick={handleClose} disabled={unsharing}>
          Cancel
        </Button>
        <Button
          onClick={handleUnshare}
          disabled={loading || error || unsharing}
          className={classes.unshareButton}
          startIcon={unsharing ? <CircularProgress size={20} /> : <LockIcon />}
        >
          {unsharing ? 'Unsharing...' : 'Unshare Project'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default UnshareProjectDialog;
